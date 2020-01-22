
import collections.abc
from typing import List, Optional, Tuple
from dataclasses import dataclass, field
from collections import OrderedDict, deque
from urllib.parse import parse_qsl
from json.decoder import JSONDecodeError

import hh
import yarl
import orjson
from tap import Tap

from .structures import CaseInsensitiveDict


@dataclass
class DataArgParseResult:
    data: List[Tuple[str, str]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# Ref: https://helpmanual.io/help/curl/
class CURLArgumentParser(Tap):
    url: str
    verbose: bool = False
    include: bool = False
    request: Optional[str] = None
    user: Optional[str] = None
    header: List[str] = []
    form: List[str] = []
    data: List[str] = []
    head: bool = False
    get: bool = False
    output: Optional[str] = None
    http2: bool = False
    # Intermediate converted data
    _url: str = ''
    _params: List[Tuple[str, str]] = []
    _data: List[Tuple[str, str]] = []
    _headers: Optional[CaseInsensitiveDict] = None
    _request_json: bool = False
    _errors: List[str] = []

    def _get_class_variables(self) -> OrderedDict:
        '''Overide to exclude our private variables'''
        all_variables = super()._get_class_variables()
        return OrderedDict((k, v) for k, v in all_variables.items() if not k.startswith('_'))

    def add_arguments(self):
        self.add_argument('url')
        self.add_argument('-v', '--verbose')
        self.add_argument('-i', '--include')
        self.add_argument('-X', '--request')
        self.add_argument('-u', '--user')
        self.add_argument('-H', '--header', nargs='?', action='append')
        self.add_argument('-d', '--data', nargs='?', action='append')
        self.add_argument('-F', '--form')
        self.add_argument('-I', '--head')
        self.add_argument('-G', '--get')
        self.add_argument('-o', '--output')
        self._headers = CaseInsensitiveDict()

    def process_args(self):
        u = yarl.URL(self.url)
        self._url = str(u.with_fragment(None))
        self._params = u.query
        self._data = deque()
        for dstring in self.data:
            result = xparse_qsl(dstring)
            self._data.extend(result.data)
            self._errors.extend(result.errors)
        for h in self.header:
            k, v = h.split(':')
            k = k.strip()     # type: str
            v = v.strip()     # type: str
            if k.lower() == hh.CONTENT_TYPE.lower() and v.lower().endswith('/json'):
                self._request_json = True
                continue
            self._headers[k] = v

    def error(self, message):
        # Override to not let it exit our program
        pass


def xparse_qsl(string: str) -> DataArgParseResult:
    # https://ec.haxx.se/http/http-post
    if not string:
        return DataArgParseResult()
    data = parse_qsl(string)
    if data:
        return DataArgParseResult(data=data)
    # Standard parse_qsl failed to parse it
    if '@' in string and not string.startswith('@'):
        # cURL spec says that the filename should already be url-encoded.
        key, filename = string.split('@')[:2]
        return DataArgParseResult(data=[(key, filename)])
    # HTTPie doesn't support sending raw content as request body
    # (though it allows to specify raw content as the value for a field),
    # so we can ignore cURL "content", "=content", "@filename" syntaxes.
    errors = deque()
    if string.startswith('@'):
        errors.append('@filename syntax (without field name) is not supported')
        return DataArgParseResult(data, errors)
    if string.startswith('='):
        errors.append('@content syntax (without field name) is not supported')
        return DataArgParseResult(data, errors)
    # Maybe JSON?
    try:
        jsdata = orjson.loads(string)
    except JSONDecodeError:
        # Not JSON
        errors.append('Cannot guess this data format')
        return DataArgParseResult(data, errors)
    if isinstance(jsdata, collections.abc.Mapping):
        data = list(jsdata.items())
        return DataArgParseResult(data, errors)
    errors.append('JSON content does not represent an object')
    return DataArgParseResult(errors=errors)
