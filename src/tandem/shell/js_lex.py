"""JS/TS 断言的保守词法近似；不执行代码，也不替代完整语法解析。"""

LINE_ENDS = frozenset("\r\n\u2028\u2029")
CONTROL_WORDS = frozenset({"if", "while", "for", "with", "switch", "catch"})
REGEX_PREFIX_WORDS = frozenset(
    {
        "return",
        "throw",
        "case",
        "delete",
        "void",
        "typeof",
        "new",
        "in",
        "of",
        "instanceof",
        "await",
        "yield",
        "else",
        "do",
    }
)
OPERATORS = (
    "===",
    "!==",
    "**=",
    "=>",
    "?.",
    "++",
    "--",
    "==",
    "!=",
    "&&",
    "||",
    "??",
    "/=",
    "<=",
    ">=",
)


def _quoted_end(code: str, start: int) -> int:
    quote = code[start]
    index = start + 1
    while index < len(code):
        if code[index] == "\\":
            index += 2
        elif code[index] == quote:
            return index + 1
        else:
            index += 1
    return len(code)


def _regex_end(code: str, start: int) -> int | None:
    index = start + 1
    character_class = False
    while index < len(code):
        char = code[index]
        if char in LINE_ENDS:
            return None
        if char == "\\":
            index += 2
            continue
        if char == "[":
            character_class = True
        elif char == "]":
            character_class = False
        elif char == "/" and not character_class:
            index += 1
            while index < len(code) and code[index].isalpha():
                index += 1
            return index
        index += 1
    return None


def _tokens(code: str) -> tuple[str, ...]:
    result: list[str] = []
    parentheses: list[bool] = []
    braces: list[bool] = []
    regex_allowed = True
    index = 0
    while index < len(code):
        char = code[index]
        previous = result[-1] if result else ""
        if char.isspace():
            index += 1
            continue
        if code.startswith("//", index):
            index += 2
            while index < len(code) and code[index] not in LINE_ENDS:
                index += 1
            continue
        if code.startswith("/*", index):
            end = code.find("*/", index + 2)
            index = len(code) if end < 0 else end + 2
            continue
        if char in "'\"`":
            index = _quoted_end(code, index)
            result.append("<literal>")
            regex_allowed = False
            continue
        if char == "/" and regex_allowed:
            end = _regex_end(code, index)
            if end is not None:
                index = end
                result.append("<literal>")
                regex_allowed = False
                continue
        if char.isalpha() or char in "_$" or char.isdigit():
            end = index + 1
            while end < len(code) and (code[end].isalnum() or code[end] in "_$"):
                end += 1
            word = code[index:end]
            result.append(word)
            regex_allowed = word in REGEX_PREFIX_WORDS and previous not in {".", "?."}
            index = end
            continue
        token = next((op for op in OPERATORS if code.startswith(op, index)), char)
        if token == "(":
            parentheses.append(previous in CONTROL_WORDS)
            regex_allowed = True
        elif token == ")":
            regex_allowed = parentheses.pop() if parentheses else False
        elif token == "{":
            braces.append(previous not in {"=", "(", "[", ",", ":", "return", "yield"})
            regex_allowed = True
        elif token == "}":
            regex_allowed = braces.pop() if braces else True
        else:
            regex_allowed = token not in {"]", ".", "?.", "++", "--"}
        result.append(token)
        index += len(token)
    return tuple(result)


def _method_declaration(tokens: tuple[str, ...], opening: int) -> bool:
    depth = 0
    for index in range(opening, len(tokens)):
        if tokens[index] == "(":
            depth += 1
        elif tokens[index] == ")":
            depth -= 1
            if depth == 0:
                return index + 1 < len(tokens) and tokens[index + 1] == "{"
    return False


def count_js_assertions(code: str) -> int:
    tokens = _tokens(code)
    count = 0
    for index, token in enumerate(tokens[:-1]):
        if token not in {"assert", "expect"}:
            continue
        previous = tokens[index - 1] if index else ""
        if previous in {"function", "class"} or (
            previous == "*" and index > 1 and tokens[index - 2] == "function"
        ):
            continue
        following = tokens[index + 1]
        if following == "(" and not _method_declaration(tokens, index + 1):
            count += 1
        elif token == "assert" and following in {".", "?."}:
            count += 1
    return count
