"""Private concrete Git read adapter. No caller-supplied Git command surface."""
from __future__ import annotations

import hashlib
import os
import re
import selectors
import shutil
import signal
import stat
import struct
import subprocess
import time

MAX_STDOUT = 2 * 1024 * 1024
MAX_STDERR = 64 * 1024


class ReadError(Exception):
    def __init__(self, code, feature=None):
        self.code, self.feature = code, feature
        super().__init__(code)


class Git:
    def __init__(self):
        self.deadline = time.monotonic() + 60
        self.binary = shutil.which('git')
        if self.binary is None:
            raise ReadError('git_missing')
        self.binary = os.path.realpath(self.binary)
        self.env = {k: v for k, v in os.environ.items()
                    if k in {'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'TZ'}}
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
                        GIT_CONFIG_SYSTEM='/dev/null', GIT_OPTIONAL_LOCKS='0',
                        GIT_TERMINAL_PROMPT='0', GIT_ATTR_NOSYSTEM='1',
                        GIT_NO_LAZY_FETCH='1')
        raw = self.run(None, '--version')
        match = re.fullmatch(rb'git version (\d+)\.(\d+)(?:\.[^\r\n ]+)?\n?', raw)
        if not match or tuple(map(int, match.groups())) < (2, 43):
            raise ReadError('unsupported_git_version')

    def run(self, root, *args, allowed=(0,), input_data=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ReadError('scan_deadline')
        argv = [self.binary, '--no-pager', '--no-optional-locks',
                '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false',
                '-c', 'core.preloadIndex=false', '-c', 'core.hooksPath=/dev/null',
                '-c', 'core.attributesFile=/dev/null', '-c', 'core.excludesFile=/dev/null',
                '-c', 'gc.auto=0', '-c', 'maintenance.auto=false']
        if root is not None:
            argv += ['-C', os.fsdecode(root)]
        argv += list(args)
        try:
            child = subprocess.Popen(argv, stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     env=self.env, cwd='/', start_new_session=True)
        except OSError:
            raise ReadError('git_failed') from None
        streams = selectors.DefaultSelector()
        data = {child.stdout: bytearray(), child.stderr: bytearray()}
        caps = {child.stdout: MAX_STDOUT, child.stderr: MAX_STDERR}
        end = time.monotonic() + min(5, remaining)
        try:
            for stream in data:
                os.set_blocking(stream.fileno(), False)
                streams.register(stream, selectors.EVENT_READ)
            pending = memoryview(input_data) if input_data is not None else None
            if pending is not None:
                os.set_blocking(child.stdin.fileno(), False)
                streams.register(child.stdin, selectors.EVENT_WRITE)
            while streams.get_map():
                left = end - time.monotonic()
                if left <= 0:
                    raise ReadError('scan_deadline' if time.monotonic() >= self.deadline else 'git_timeout')
                for key, _ in streams.select(min(left, .1)):
                    if key.fileobj is child.stdin:
                        try:
                            sent = os.write(child.stdin.fileno(), pending[:4096]) if pending else 0
                            pending = pending[sent:]
                        except BrokenPipeError:
                            pending = pending[:0]
                        if not pending:
                            streams.unregister(child.stdin)
                            child.stdin.close()
                        continue
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        streams.unregister(key.fileobj)
                    else:
                        data[key.fileobj].extend(chunk)
                        if len(data[key.fileobj]) > caps[key.fileobj]:
                            raise ReadError('command_output_limit')
            # Observe exit without reaping: retaining the child PID until group cleanup
            # prevents that ID being recycled into an unrelated process group.
            while True:
                exited = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if exited is not None:
                    code = exited.si_status if exited.si_code == os.CLD_EXITED else -exited.si_status
                    break
                if time.monotonic() >= end:
                    raise ReadError('scan_deadline' if time.monotonic() >= self.deadline else 'git_timeout')
                time.sleep(.001)
            if code not in allowed:
                raise ReadError('git_failed')
            return bytes(data[child.stdout])
        finally:
            # A child may have closed its pipes and left a descendant. Own only this group.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            streams.close()
            child.stdout.close()
            child.stderr.close()
            if child.stdin is not None:
                child.stdin.close()

    def configuration(self, root):
        # Do not invoke repository-aware Git to locate config: even rev-parse
        # follows includes during setup. Resolve only Git's bounded pointer files.
        marker = os.path.join(root, b'.git')
        samples = []
        try:
            mode = os.lstat(marker).st_mode
        except FileNotFoundError:
            if not os.path.isdir(root):
                raise ReadError('git_failed') from None
            if not os.path.isfile(os.path.join(root, b'HEAD')) or not os.path.isdir(os.path.join(root, b'objects')):
                raise ReadError('repository_unavailable') from None
            gd = root  # Bare candidate; classify only after checking its config.
        except OSError:
            raise ReadError('checkout_unavailable') from None
        else:
            if stat.S_ISDIR(mode):
                gd = marker
            elif stat.S_ISREG(mode):
                pointer = bounded_file(marker, 4096, 'config_limit', self.deadline)
                samples.append((marker, (hashlib.sha256(pointer).hexdigest(), len(pointer))))
                if not pointer.startswith(b'gitdir: '):
                    raise ReadError('repository_unavailable')
                path = pointer[8:].removesuffix(b'\n')
                if not path or b'\0' in path:
                    raise ReadError('repository_unavailable')
                gd = os.path.realpath(os.path.join(root, path))
            else:
                raise ReadError('unsupported_repository_feature', 'unproven_read_effect')
        common_file = os.path.join(gd, b'commondir')
        pointer = bounded_file(common_file, 4096, 'config_limit', self.deadline, optional=True)
        samples.append((common_file, None if pointer is None else (hashlib.sha256(pointer).hexdigest(), len(pointer))))
        common = gd
        if pointer is not None:
            path = pointer.removesuffix(b'\n')
            if not path or b'\0' in path:
                raise ReadError('repository_unavailable')
            common = os.path.realpath(os.path.join(gd, path))
        paths = sorted({os.path.join(gd, b'config.worktree'), os.path.join(common, b'config')})
        configs, remaining = [], 1024*1024
        for p in paths:
            raw = bounded_file(p, remaining, 'config_limit', self.deadline, optional=True)
            configs.append((p, raw))
            if raw is not None:
                remaining -= len(raw)
        keys = []
        for p, raw in configs:
            samples.append((p, None if raw is None else (hashlib.sha256(raw).hexdigest(), len(raw))))
            if raw is not None:
                # Parse the bounded snapshot, with no repo setup and no includes.
                # Only key names leave Git; config values never enter the report.
                parsed = self.run(None, 'config', '--file', '-', '--no-includes', '--null',
                                  '--name-only', '--list', input_data=raw)
                keys.extend(x.lower() for x in parsed.split(b'\0') if x)
        return gd, common, tuple(sorted(samples)), keys

    def preflight(self, root):
        gd, common, config, keys = self.configuration(root)
        for key in keys:
            if key.startswith(b'filter.'):
                raise ReadError('unsupported_repository_feature', 'content_filter')
            if key.startswith((b'include.', b'includeif.')):
                raise ReadError('unsupported_repository_feature', 'included_config')
            if key.startswith(b'submodule.'):
                raise ReadError('unsupported_repository_feature', 'submodule')
            if key.startswith(b'core.sparse'):
                raise ReadError('unsupported_repository_feature', 'sparse')
            if key == b'extensions.partialclone' or (key.startswith(b'remote.') and key.endswith(b'.promisor')):
                raise ReadError('unsupported_repository_feature', 'partial_clone')
        if self.line(root, 'rev-parse', '--is-bare-repository') == b'true':
            raise ReadError('unsupported_repository_feature', 'bare')
        if (self.line(root, 'rev-parse', '--absolute-git-dir') != gd or
                self.line(root, 'rev-parse', '--path-format=absolute', '--git-common-dir') != common):
            raise ReadError('state_changed')
        algorithm = self.line(root, 'rev-parse', '--show-object-format')
        if algorithm not in (b'sha1', b'sha256'):
            raise ReadError('unsupported_repository_feature', 'unproven_read_effect')
        index = fingerprint(os.path.join(gd, b'index'), 128 * 1024 * 1024, 'index_limit',
                            optional=True, deadline=self.deadline, index_algorithm=algorithm.decode())
        return config, index

    def line(self, root, *args, allowed=(0,)):
        raw = self.run(root, *args, allowed=allowed)
        # Git path queries add exactly one LF; embedded path newlines are data.
        if not raw.endswith(b'\n'):
            raise ReadError('status_parse_error')
        return raw[:-1]

    def identify(self, root):
        self.preflight(root)
        top = self.line(root, 'rev-parse', '--show-toplevel')
        if os.path.realpath(top) != root:
            raise ReadError('repository_unavailable')
        return os.path.realpath(self.line(root, 'rev-parse', '--path-format=absolute', '--git-common-dir'))

    def registrations(self, root):
        raw = self.run(root, 'worktree', 'list', '--porcelain', '-z')
        if not raw.endswith(b'\0\0'):
            raise ReadError('status_parse_error')
        rows = []
        for group in raw.split(b'\0\0')[:-1]:
            fields = group.split(b'\0')
            if not fields[0].startswith(b'worktree '):
                raise ReadError('status_parse_error')
            path = fields[0][9:]
            if not os.path.isabs(path):
                raise ReadError('status_parse_error')
            rows.append((os.path.realpath(path), tuple(sorted(fields[1:]))))
        if len({p for p, _ in rows}) != len(rows):
            raise ReadError('status_parse_error')
        return tuple(sorted(rows))

    def head(self, root):
        oid = self.run(root, 'rev-parse', '--verify', '--quiet', 'HEAD', allowed=(0, 1)).rstrip(b'\n')
        branch = self.run(root, 'symbolic-ref', '--quiet', 'HEAD', allowed=(0, 1)).rstrip(b'\n')
        if oid and (len(oid) not in (40, 64) or not re.fullmatch(rb'[0-9a-f]+', oid)):
            raise ReadError('status_parse_error')
        if not oid and not branch:
            raise ReadError('git_failed')
        return {'state': 'commit' if oid else 'unborn', 'oid': oid.decode() if oid else None,
                'branch_bytes': branch or None}

    def sample(self, root):
        cfg, index = self.preflight(root)
        head = self.head(root)
        raw = self.run(root, 'status', '--porcelain=v2', '-z', '--untracked-files=all', '--ignore-submodules=all')
        paths, renames = parse_status(raw)
        return {'config': cfg, 'index': index, 'head': head, 'status': raw,
                'paths': paths, 'renames': renames}


def bounded_file(path, limit, code, deadline, optional=False):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except FileNotFoundError:
        if optional:
            return None
        raise ReadError('checkout_unavailable') from None
    except OSError:
        raise ReadError('checkout_unavailable') from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ReadError('checkout_unavailable')
        if info.st_size > limit:
            raise ReadError(code)
        raw = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise ReadError('scan_deadline')
            chunk = os.read(fd, min(65536, limit+1-len(raw)))
            if not chunk:
                return bytes(raw)
            raw.extend(chunk)
            if len(raw) > limit:
                raise ReadError(code)
    except OSError:
        raise ReadError('checkout_unavailable') from None
    finally:
        os.close(fd)


def fingerprint(path, limit, code, optional=False, deadline=None, index_algorithm=None):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except FileNotFoundError:
        if optional:
            return None
        raise ReadError('checkout_unavailable') from None
    except OSError:
        raise ReadError('checkout_unavailable') from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ReadError('checkout_unavailable')
        if info.st_size > limit:
            raise ReadError(code)
        digest = hashlib.sha256()
        index_data = bytearray() if index_algorithm is not None else None
        count = 0
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                raise ReadError('scan_deadline')
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            count += len(chunk)
            if count > limit:
                raise ReadError(code)
            digest.update(chunk)
            if index_data is not None:
                index_data.extend(chunk)
        if index_data is not None:
            check_index(index_data, index_algorithm, deadline)
        return digest.hexdigest(), count
    except OSError:
        raise ReadError('checkout_unavailable') from None
    finally:
        os.close(fd)


def check_index(data, algorithm, deadline):
    """Locate extensions without Git opening/freshening a shared index.

    Format: https://git-scm.com/docs/gitformat-index (versions 2, 3, 4).
    No entry content or configuration value is returned to the report.
    """
    width = 20 if algorithm == 'sha1' else 32
    end = len(data)-width
    if end < 12 or data[:4] != b'DIRC':
        raise ReadError('status_parse_error')
    version, count = struct.unpack('!II', data[4:12])
    if version not in (2, 3, 4):
        raise ReadError('unsupported_repository_feature', 'unproven_read_effect')
    if hashlib.new(algorithm, data[:end]).digest() != data[end:]:
        raise ReadError('status_parse_error')
    pos = 12
    for _ in range(count):
        if deadline is not None and time.monotonic() >= deadline:
            raise ReadError('scan_deadline')
        start = pos
        fixed = 42+width
        if pos+fixed > end:
            raise ReadError('status_parse_error')
        if int.from_bytes(data[pos+24:pos+28], 'big') & 0o170000 == 0o160000:
            raise ReadError('unsupported_repository_feature', 'submodule')
        flags = int.from_bytes(data[pos+40+width:pos+fixed], 'big')
        if flags & 0x8000:  # assume-valid can suppress modified tracked paths.
            raise ReadError('unsupported_repository_feature', 'unproven_read_effect')
        pos += fixed
        if flags & 0x4000:
            if version == 2 or pos+2 > end:
                raise ReadError('status_parse_error')
            extended = int.from_bytes(data[pos:pos+2], 'big')
            # Intent-to-add is observable; skip-worktree and unknown flags are not.
            if extended & ~0x2000:
                raise ReadError('unsupported_repository_feature', 'unproven_read_effect')
            pos += 2
        if version == 4:
            # Skip the bounded prefix-removal varint; paths themselves remain Git's job.
            for _ in range(10):
                if pos >= end:
                    raise ReadError('status_parse_error')
                byte = data[pos]; pos += 1
                if not byte & 0x80:
                    break
            else:
                raise ReadError('status_parse_error')
        nul = data.find(b'\0', pos, end)
        if nul < 0:
            raise ReadError('status_parse_error')
        pos = nul+1
        if version != 4:
            pos = start+((pos-start+7)//8)*8
        if pos > end:
            raise ReadError('status_parse_error')
    while pos < end:
        if end-pos < 8:
            raise ReadError('status_parse_error')
        signature = bytes(data[pos:pos+4])
        size = int.from_bytes(data[pos+4:pos+8], 'big')
        if signature in (b'link', b'sdir'):
            raise ReadError('unsupported_repository_feature', 'split_index' if signature == b'link' else 'sparse')
        if not 65 <= signature[0] <= 90:
            raise ReadError('unsupported_repository_feature', 'unproven_read_effect')
        pos += 8+size
        if pos > end:
            raise ReadError('status_parse_error')


def validate_path(raw):
    if not raw or raw.startswith(b'/') or any(x in (b'', b'.', b'..') for x in raw.split(b'/')):
        raise ReadError('status_parse_error')
    return raw


def parse_status(raw):
    if raw and not raw.endswith(b'\0'):
        raise ReadError('status_parse_error')
    records = iter(raw.split(b'\0')[:-1])
    paths, renames = set(), []
    for record in records:
        kind = record[:1]
        if kind == b'?':
            if not record.startswith(b'? '):
                raise ReadError('status_parse_error')
            paths.add(validate_path(record[2:]))
            if len(paths) > 4096:
                raise ReadError('path_limit')
            continue
        if kind not in (b'1', b'2', b'u'):
            raise ReadError('status_parse_error')
        fields = record.split(b' ', {b'1': 8, b'2': 9, b'u': 10}[kind])
        if len(fields) != {b'1': 9, b'2': 10, b'u': 11}[kind]:
            raise ReadError('status_parse_error')
        if not re.fullmatch(rb'[.MTADRCU]{2}', fields[1]) or fields[2] != b'N...':
            raise ReadError('status_parse_error')
        modes = fields[3:7] if kind == b'u' else fields[3:6]
        hashes = fields[7:10] if kind == b'u' else fields[6:8]
        if any(not re.fullmatch(rb'[0-7]{6}', x) for x in modes):
            raise ReadError('status_parse_error')
        if any(not re.fullmatch(rb'(?:[0-9a-f]{40}|[0-9a-f]{64})', x) for x in hashes):
            raise ReadError('status_parse_error')
        dest = validate_path(fields[-1]); paths.add(dest)
        if kind == b'2':
            score = fields[8]
            if not re.fullmatch(rb'[RC](?:100|[0-9]{1,2})', score):
                raise ReadError('status_parse_error')
            try:
                source = validate_path(next(records))
            except StopIteration:
                raise ReadError('status_parse_error') from None
            paths.add(source)
            renames.append((source, dest, 'rename' if score[:1] == b'R' else 'copy'))
        if len(paths) > 4096:
            raise ReadError('path_limit')
    return tuple(sorted(paths)), tuple(sorted(renames))
