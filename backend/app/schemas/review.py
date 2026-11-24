from datetime import datetime

from pydantic import BaseModel


class TaskOut(BaseModel):
    id: int
    contract_id: int
    contract_name: str
    thread_id: str
    status: str
    current_node: str
    error_msg: str
    create_time: datetime
    finish_time: datetime | None


class FeedbackAction(BaseModel):
    suggestion_id: int
    action: str  # accept / reject / edit
    edited_text: str | None = None
    comment: str | None = None


class FeedbackRequest(BaseModel):
    actions: list[FeedbackAction]
