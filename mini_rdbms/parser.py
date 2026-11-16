"""Phase 1 SQL statement boundaries and parsing."""

from collections.abc import Iterator

from .errors import SqlSyntaxError
from .models import InsertQuery, Query, SelectQuery, WhereCondition


class _Reader:
    """Read SQL directly without constructing an intermediate token list."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.position = 0

    def peek(self) -> str:
        return self.text[self.position:self.position + 1]

    def whitespace(self, *, required: bool = False) -> bool:
        start = self.position
        while self.peek() and self.peek() in " \t\r\n":
            self.position += 1
        consumed = self.position != start
        if required and not consumed:
            raise SqlSyntaxError("Expected whitespace")
        return consumed

    def symbol(self, symbol: str) -> bool:
        if self.text.startswith(symbol, self.position):
            self.position += len(symbol)
            return True
        return False

    def expect_symbol(self, symbol: str) -> None:
        if not self.symbol(symbol):
            raise SqlSyntaxError(f"Expected {symbol}")

    def keyword(self, word: str) -> bool:
        end = self.position + len(word)
        if self.text[self.position:end].upper() != word:
            return False
        # A keyword cannot be a prefix of another word.
        following = self.text[end:end + 1]
        if following and (following.isalnum() or following == "_"):
            return False
        self.position = end
        return True

    def expect_keyword(self, word: str) -> None:
        if not self.keyword(word):
            raise SqlSyntaxError(f"Expected {word}")

    def quoted(self, quote: str) -> str:
        self.expect_symbol(quote)
        result: list[str] = []
        while self.peek():
            char = self.peek()
            self.position += 1
            if char in "\r\n":
                raise SqlSyntaxError("Newline inside quoted text")
            if char == quote:
                if self.symbol(quote):
                    result.append(quote)
                    continue
                return "".join(result)
            result.append(char)
        raise SqlSyntaxError("Unterminated quoted text")

    def name(self) -> str:
        name = self.quoted('"').strip()
        if not name:
            raise SqlSyntaxError("Empty identifier")
        return name

    def value(self) -> int | str | None:
        if self.peek() == "'":
            return self.quoted("'")
        if self.keyword("NULL"):
            return None
        start = self.position
        if self.peek() in ("+", "-"):
            self.position += 1
        digit_start = self.position
        while self.peek() and self.peek() in "0123456789":
            self.position += 1
        if self.position == digit_start:
            raise SqlSyntaxError("Expected value")
        try:
            return int(self.text[start:self.position])
        except ValueError as error:
            raise SqlSyntaxError("Invalid integer") from error

class _Parser:
    """Recognize SQL structure using the reader's lexical operations."""

    def __init__(self, reader: _Reader) -> None:
        self.reader = reader

    def insert(self) -> InsertQuery:
        reader = self.reader
        reader.whitespace(required=True)
        reader.expect_keyword("INTO")
        reader.whitespace(required=True)
        table = reader.name()
        reader.whitespace(required=True)
        reader.expect_keyword("VALUES")
        reader.whitespace()
        reader.expect_symbol("(")
        reader.whitespace()
        values = [reader.value()]
        reader.whitespace()
        while reader.symbol(","):
            reader.whitespace()
            values.append(reader.value())
            reader.whitespace()
        reader.expect_symbol(")")
        return InsertQuery(table, values)

    def condition(self) -> WhereCondition:
        reader = self.reader
        column = reader.name()
        had_space = reader.whitespace()
        if had_space and reader.keyword("IS"):
            reader.whitespace(required=True)
            negated = reader.keyword("NOT")
            if negated:
                reader.whitespace(required=True)
            reader.expect_keyword("NULL")
            return (column, "IS NOT NULL" if negated else "IS NULL", None)
        for operator in ("!=", ">=", "<=", "=", ">", "<"):
            if reader.symbol(operator):
                reader.whitespace()
                return (column, operator, reader.value())
        raise SqlSyntaxError("Expected comparison operator")

    def select(self) -> SelectQuery:
        reader = self.reader
        reader.whitespace(required=True)
        columns: list[str] | None
        if reader.symbol("*"):
            columns = None
            reader.whitespace(required=True)
        else:
            columns = [reader.name()]
            while True:
                had_space = reader.whitespace()
                if not reader.symbol(","):
                    if not had_space:
                        raise SqlSyntaxError("Expected whitespace")
                    break
                reader.whitespace()
                columns.append(reader.name())
        reader.expect_keyword("FROM")
        reader.whitespace(required=True)
        table = reader.name()
        where: list[WhereCondition] = []
        if reader.whitespace() and reader.keyword("WHERE"):
            reader.whitespace(required=True)
            where.append(self.condition())
            while True:
                if not reader.whitespace() or not reader.keyword("AND"):
                    break
                reader.whitespace(required=True)
                where.append(self.condition())
        return SelectQuery(table, columns, where)


def parse_queries(sql_text: str) -> Iterator[Query]:
    """Parse and yield one query at a time, without examining later statements."""
    reader = _Reader(sql_text)
    parser = _Parser(reader)
    while True:
        reader.whitespace()
        if not reader.peek():
            return
        if reader.symbol(";"):
            continue
        if reader.keyword("INSERT"):
            query: Query = parser.insert()
        elif reader.keyword("SELECT"):
            query = parser.select()
        else:
            raise SqlSyntaxError("Expected INSERT or SELECT")
        reader.whitespace()
        reader.expect_symbol(";")
        yield query
