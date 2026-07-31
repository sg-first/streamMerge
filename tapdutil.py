import requests
import sys
import os
import json
if sys.version_info[0] > 2:
    import configparser
    config = configparser.ConfigParser()
else:
    import ConfigParser
    config = ConfigParser.ConfigParser()
import re


def _find_config_path():
    """
    定位 tapdconfig.ini，按优先级查找：
    1. 打包后 exe 所在目录（最常用，用户可直接在 exe 旁改配置）
    2. 源码/脚本所在目录（开发时运行）
    3. PyInstaller 解包目录 sys._MEIPASS（配置被打成包内 data 时）
    """
    candidates = []

    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后：exe 目录
        candidates.append(os.path.join(os.path.dirname(sys.executable), 'tapdconfig.ini'))
        # 以及资源解包目录（onefile 模式）
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            candidates.append(os.path.join(meipass, 'tapdconfig.ini'))

    # 源码/脚本目录
    candidates.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'tapdconfig.ini'))

    # 返回结果
    for path in candidates:
        if os.path.exists(path):
            return path
    # 找不到时返回优先级最高的路径，便于调用方/print 提示用户该去哪放配置
    return candidates[0]


class TapdEnv:
    def __init__(self, in_Config = "", in_ProjectID = "", in_StoryIdPrefix = "", in_AppID = "", in_AppKey="", in_URL=""):
        if not in_Config:
            in_Config = _find_config_path()
        if os.path.exists(in_Config):
            config.read(in_Config)
            self.ProjectID = config.get("config", "ProjectID")
            self.StoryIdPrefix = config.get("config", "StoryIdPrefix")
            self.AppID = config.get("config", "AppID")
            self.AppKey = config.get("config", "AppKey")
            self.URL = config.get("config", "URL")
        else:
            print(f"{in_Config}  {in_ProjectID}  {in_StoryIdPrefix}  {in_AppID}  {in_AppKey}  {in_URL}")
            print("there is no config file")


        if in_ProjectID != "":
            self.ProjectID = in_ProjectID
        if in_StoryIdPrefix != "":
            self.StoryIdPrefix = in_StoryIdPrefix
        if in_AppID != "":
            self.AppID = in_AppID
        if in_AppKey != "":
            self.AppKey = in_AppKey
        if in_URL != "":
            self.URL = in_URL


def _parse_tapd_json(text):
    """Manually parse JSON string into Python object, tolerating invalid escape sequences."""
    pos = [0]  # use list for mutability in nested functions

    def skip_whitespace():
        while pos[0] < len(text) and text[pos[0]] in ' \t\n\r':
            pos[0] += 1

    def parse_value():
        skip_whitespace()
        if pos[0] >= len(text):
            raise ValueError("Unexpected end of input")
        ch = text[pos[0]]
        if ch == '{':
            return parse_object()
        elif ch == '[':
            return parse_array()
        elif ch == '"':
            return parse_string()
        elif ch == 't':
            return parse_literal('true', True)
        elif ch == 'f':
            return parse_literal('false', False)
        elif ch == 'n':
            return parse_literal('null', None)
        else:
            return parse_number()

    def parse_object():
        obj = {}
        pos[0] += 1  # skip '{'
        skip_whitespace()
        if pos[0] < len(text) and text[pos[0]] == '}':
            pos[0] += 1
            return obj
        while True:
            skip_whitespace()
            key = parse_string()
            skip_whitespace()
            if text[pos[0]] != ':':
                raise ValueError(f"Expected ':' at pos {pos[0]}")
            pos[0] += 1
            value = parse_value()
            obj[key] = value
            skip_whitespace()
            if pos[0] >= len(text):
                break
            if text[pos[0]] == '}':
                pos[0] += 1
                break
            elif text[pos[0]] == ',':
                pos[0] += 1
        return obj

    def parse_array():
        arr = []
        pos[0] += 1  # skip '['
        skip_whitespace()
        if pos[0] < len(text) and text[pos[0]] == ']':
            pos[0] += 1
            return arr
        while True:
            value = parse_value()
            arr.append(value)
            skip_whitespace()
            if pos[0] >= len(text):
                break
            if text[pos[0]] == ']':
                pos[0] += 1
                break
            elif text[pos[0]] == ',':
                pos[0] += 1
        return arr

    def parse_string():
        pos[0] += 1  # skip opening '"'
        result = []
        valid_escapes = {'"': '"', '\\': '\\', '/': '/', 'b': '\b',
                         'f': '\f', 'n': '\n', 'r': '\r', 't': '\t'}
        while pos[0] < len(text):
            ch = text[pos[0]]
            if ch == '\\':
                pos[0] += 1
                if pos[0] >= len(text):
                    break
                esc = text[pos[0]]
                if esc == 'u':
                    # unicode escape \uXXXX
                    hex_str = text[pos[0]+1:pos[0]+5]
                    if len(hex_str) == 4 and all(c in '0123456789abcdefABCDEF' for c in hex_str):
                        result.append(chr(int(hex_str, 16)))
                        pos[0] += 5
                    else:
                        result.append('\\u')
                        pos[0] += 1
                elif esc in valid_escapes:
                    result.append(valid_escapes[esc])
                    pos[0] += 1
                else:
                    # Invalid escape: keep backslash and character as-is
                    result.append('\\')
                    result.append(esc)
                    pos[0] += 1
            elif ch == '"':
                pos[0] += 1  # skip closing '"'
                break
            else:
                result.append(ch)
                pos[0] += 1
        return ''.join(result)

    def parse_literal(literal, value):
        if text[pos[0]:pos[0]+len(literal)] == literal:
            pos[0] += len(literal)
            return value
        raise ValueError(f"Invalid literal at pos {pos[0]}")

    def parse_number():
        start = pos[0]
        if pos[0] < len(text) and text[pos[0]] == '-':
            pos[0] += 1
        while pos[0] < len(text) and text[pos[0]].isdigit():
            pos[0] += 1
        if pos[0] < len(text) and text[pos[0]] == '.':
            pos[0] += 1
            while pos[0] < len(text) and text[pos[0]].isdigit():
                pos[0] += 1
        if pos[0] < len(text) and text[pos[0]] in 'eE':
            pos[0] += 1
            if pos[0] < len(text) and text[pos[0]] in '+-':
                pos[0] += 1
            while pos[0] < len(text) and text[pos[0]].isdigit():
                pos[0] += 1
        num_str = text[start:pos[0]]
        return float(num_str) if '.' in num_str or 'e' in num_str or 'E' in num_str else int(num_str)

    return parse_value()


def VisitTapd(tapd_env, story_type, story_id, fields):
    story_ids = []
    if isinstance(story_id, (int)):
        story_ids.append(str(story_id))
    elif isinstance(story_id, (str)):
        story_ids.append(story_id)
    elif isinstance(story_id, list):
        story_ids = story_id

    id_str = ','.join(f'{tapd_env.StoryIdPrefix}{sid}' for sid in story_ids)
    url = f'{tapd_env.URL}/{story_type}?workspace_id={tapd_env.ProjectID}&id={id_str}&fields={fields}'
    r = requests.get(url, auth=(tapd_env.AppID, tapd_env.AppKey))
    r.encoding = 'unicode-escape'
    try:
        data = json.loads(r.text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        print(f"json.loads failed, try _parse_tapd_json!!!!!!!!!!!!!!!!!!")
        try:
            data = _parse_tapd_json(r.text)
        except Exception as e:
            print(f"JsonDecode Failed: {e}\n{r.text}")
            return []
    if data["status"] != 1:
        print(f"VisitTapd Failed, errorcode:{data['status']}")
        return []
    return data["data"]



def BugHasSolved(story_id):
    tapd_env = TapdEnv()
    ret = VisitTapd(tapd_env, 'bugs', story_id, 'status')
    status = ret[0]['Bug']['status'] if ret and ret[0].get('Bug', {}).get('status') else None
    return status == 'resolved'

def IsChildOf(child_id, parent_id):
    tapd_env = TapdEnv()
    ret = VisitTapd(tapd_env, 'stories', child_id, 'parent_id')
    real_parent_id = ret[0]['Story']['parent_id'] if ret and ret[0].get('Story', {}).get('parent_id') else None
    prefix = tapd_env.StoryIdPrefix
    real_parent_id = real_parent_id[len(prefix):] if real_parent_id.startswith(prefix) else real_parent_id
    return real_parent_id == parent_id


def FindChildrenIDs(story_id):
    tapd_env = TapdEnv()
    visited = set()
    result_list = []

    def _collect(sid):
        sid = str(sid)
        if sid in visited:
            return
        visited.add(sid)
        result_list.append(sid)
        ret = VisitTapd(tapd_env, 'stories', sid, 'children_id')
        children_id = ret[0]['Story']['children_id'] if ret and ret[0].get('Story', {}).get('children_id') else None
        if children_id:
            prefix = tapd_env.StoryIdPrefix
            for child in children_id.split('|'):
                if not child:
                    continue
                child = child[len(prefix):] if child.startswith(prefix) else child
                if not IsChildOf(child, sid):
                    print(f"Warning: {child} is not child of {sid}!!!!!!!")
                    continue
                _collect(child)

    _collect(story_id)
    return result_list

def GetStoryUrlFromId(story_id):
    tapd_env = TapdEnv()
    ret = VisitTapd(tapd_env, 'stories', story_id, 'name')
    title = ret[0]['Story']['name'] if ret and ret[0].get('Story', {}).get('name') else None
    return f'--story={story_id} {title} https://tapd.woa.com/r/t?id={story_id}&type=story'

def GetBugUrlFromId(bug_id):
    tapd_env = TapdEnv()
    ret = VisitTapd(tapd_env, 'bugs', bug_id, 'title')
    title = ret[0]['Bug']['title'] if ret and ret[0].get('Bug', {}).get('title') else None
    return f'--bug={bug_id} {title} https://tapd.woa.com/r/t?id={bug_id}&type=bug'

def GetUrlFromId(id):
    tapd_env = TapdEnv()

    ret = VisitTapd(tapd_env, 'stories', id, 'name')
    title = ret[0]['Story']['name'] if ret and ret[0].get('Story', {}).get('name') else None
    url_str = f'--story={id} {title} https://tapd.woa.com/r/t?id={id}&type=story'

    if not title:
        ret = VisitTapd(tapd_env, 'bugs', id, 'title')
        title = ret[0]['Bug']['title'] if ret and ret[0].get('Bug', {}).get('title') else None
        url_str = f'--bug={id} {title} https://tapd.woa.com/r/t?id={id}&type=bug'

    return url_str


def GetBugOwner(bug_id):
    tapd_env = TapdEnv()
    ret = VisitTapd(tapd_env, 'bugs', bug_id, 'current_owner')
    owner = ret[0]['Bug']['current_owner'] if ret and ret[0].get('Bug', {}).get('current_owner') else None
    return owner

