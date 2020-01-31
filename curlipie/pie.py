import re
import shlex
import logging
import mimetypes
from shlex import quote
from collections import deque
from typing import List

import hh
import attr
from .compat import json_dump
from .curly import CURLArgumentParser


REGEX_SINGLE_OPT = re.compile(r'-\w$')
logger = logging.getLogger(__name__)


@attr.s(auto_attribs=True)
class ConversionResult:
    httpie: str
    errors: List[str] = attr.Factory(list)


def join_previous_arg(cmds: List[str], name: str):
    prev_arg = cmds[-1]
    if REGEX_SINGLE_OPT.match(prev_arg):
        cmds[-1] += name
    else:
        cmds.append(f'-{name}')


def curl_to_httpie(cmd: str, long_option: bool = False) -> ConversionResult:
    # The cmd can be multiline string, with escape symbols, shlex doesn't support it, so
    # we should convert it to one-line first.
    oneline = ''.join(cmd.splitlines())
    try:
        cargs = shlex.split(oneline)
    except ValueError as e:
        logger.error('Failed to parse as shell command. Error: %s', e)
        return ConversionResult('', errors=[str(e)])
    if not cargs:
        return ConversionResult('')
    if cargs[0] == 'curl':
        cargs = cargs[1:]
        if not cargs:
            return ConversionResult('http')
    args = CURLArgumentParser().parse_args(cargs)
    cmds = deque(['http'])
    if args.verbose:
        cmds.append('--verbose' if long_option else '-v')
    if args.location:
        if long_option:
            cmds.append('--follow')
        else:
            join_previous_arg(cmds, 'F')
    if args.remote_name:
        if long_option:
            cmds.append('--download')
        else:
            join_previous_arg(cmds, 'd')
    if args._data and not args._request_json:
        if long_option:
            cmds.append('--form')
        else:
            join_previous_arg(cmds, 'f')
    if args.user or args._basic_auth:
        user = args.user or args._basic_auth
        if long_option:
            cmds.extend(('--auth', user))
        else:
            join_previous_arg(cmds, 'a')
            cmds.append(user)
    if args.include:
        cmds.append('--all')
    if args.insecure:
        cmds.append('--verify', 'no')
    if args.max_redirs:
        cmds.extend('--max-redirects', args.max_redirs)
    if args.max_time:
        cmds.extend('--timeout', args.max_time)
    if args.head:
        cmds.append('HEAD')
    elif args.request and not (args._data and args.request == 'POST'):
        cmds.append(args.request)
    # URL
    cmds.append(args._url)
    # Headers
    for k, v in args._headers.items():
        cmds.append(f'{quote(k)}:{quote(v)}')
    if args._request_json and not args._data:
        mime = mimetypes.types_map['.json']
        cmds.append(f'{quote(hh.CONTENT_TYPE)}:{quote(mime)}')
    if args.user_agent:
        cmds.append(f'{hh.USER_AGENT}:{quote(args.user_agent)}')
    # Params
    for k, v in args._params:
        if k.startswith('-'):
            cmds.append('--')
        k = k.replace('=', r'\=')
        cmds.append(f'{quote(k)}=={quote(v)}')
    # Data
    for p, v in args._data:
        p = str(p)
        if p.startswith('-'):
            cmds.append('--')
        p = p.replace('=', r'\=')
        qp = quote(p)
        # Syntax for uploading file
        if isinstance(v, str) and v.startswith('@') and not args._request_json:
            cmds.append(f'{qp}@{quote(v)}')
            continue
        # Not uploading file
        # Python shlex's quote will turn bool value to empty string, that is not we want
        if isinstance(v, bool):
            js_bool = str(v).lower()
            cmds.append(f'{qp}:={js_bool}' if not args.get else f'{qp}=={str(v)}')
            continue
        try:
            qv = quote(v)
            cmds.append(f'{qp}={qv}' if not args.get else f'{qp}=={qv}')
        except TypeError:     # v is not string, normally after parsed from JSON
            if isinstance(v, (list, dict)):
                v = quote(json_dump(v))
            cmds.append(f'{qp}:={v}' if not args.get else f'{qp}=={quote(str(v))}')
    if args.output:
        param = '-o' if not long_option else '--output'
        cmds.extend((param, quote(args.output)))
    return ConversionResult(' '.join(cmds), args._errors)
