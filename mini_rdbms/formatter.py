"""Format execution results for the command line."""

from .models import ExecutionResult, InsertResult


def format_result(result: ExecutionResult) -> str:
    """Return the display text for an execution result."""
    if isinstance(result, InsertResult):
        return f"INSERT OK (id={result.inserted_id})"

    rows = [
        ["NULL" if value is None else str(value) for value in row]
        for row in result.rows
    ]
    widths = [
        max([len(column), *(len(row[index]) for row in rows)])
        for index, column in enumerate(result.columns)
    ]
    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"

    def format_row(row: list[str]) -> str:
        return "|" + "|".join(
            f" {value:<{width}} " for value, width in zip(row, widths)
        ) + "|"

    lines = [border, format_row(result.columns), border]
    lines.extend(format_row(row) for row in rows)
    if rows:
        lines.append(border)
    count = len(rows)
    lines.append(f"({count} {'row' if count == 1 else 'rows'})")
    return "\n".join(lines)
