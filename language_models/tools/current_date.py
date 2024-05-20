"""Current date tool."""

from datetime import datetime

from language_models.tools.tool import Tool


def current_date() -> datetime:
    return datetime.now()


current_date_tool = Tool(
    func=current_date,
    name="Current Date",
    description="Use this tool to access the current local date and time.",
)
