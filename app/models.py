from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectInput(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    question: str = Field(min_length=5, max_length=6000)
    constraints: str = Field(default="", max_length=3000)


class SourceInput(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl | None = None
    text: str = Field(min_length=20, max_length=20000)
    locator: str = Field(default="User supplied passage", max_length=300)


class FeedbackInput(StrictModel):
    expected_revision: int = Field(ge=1)
    kind: Literal["correction", "preference", "constraint", "instruction"]
    text: str = Field(min_length=1, max_length=4000)
    direction_id: str | None = None


class RunInput(StrictModel):
    max_calls: int = Field(default=4, ge=1, le=12)
    max_tokens: int = Field(default=45000, ge=5000, le=250000)
    max_minutes: int = Field(default=15, ge=1, le=120)
    use_search: bool = True


class Mechanism(StrictModel):
    object: str
    locus: str
    operation: str
    output: str
    signal: str
    assumptions: list[str]


class Claim(StrictModel):
    text: str
    status: Literal["proposed", "inferred", "supported", "contested"]
    source_ids: list[str]


class Comparison(StrictModel):
    source_id: str
    shared_foundation: str
    difference: str
    next_opportunity: str


class Direction(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    title: str = Field(min_length=1, max_length=200)
    question: str
    innovation: str
    impact: str
    feasibility: str
    mechanism: Mechanism
    claims: list[Claim]
    comparisons: list[Comparison]
    unknowns: list[str]
    next_step: str


class ResearchStep(StrictModel):
    summary: str
    directions: list[Direction] = Field(min_length=1, max_length=4)
    next_action: Literal["search", "develop", "finish"]
    search_query: str
    rationale: str


class SelectionInput(StrictModel):
    expected_revision: int
    selection: Literal["exploring", "retained", "parked"]


class MemoryInput(StrictModel):
    statement: str = Field(min_length=5, max_length=3000)
    conditions: str = Field(min_length=1, max_length=3000)
    source_ids: list[str] = Field(default_factory=list, max_length=20)


class CommandInput(StrictModel):
    command: Literal["pause", "resume", "cancel"]


class ProviderInput(StrictModel):
    api_base: HttpUrl
    api_key: SecretStr | None = None
    model: str = Field(min_length=1, max_length=200)
    output_mode: Literal["json_schema", "json_object", "text"]
    token_parameter: Literal["max_tokens", "max_completion_tokens"]
    max_output: int = Field(ge=1000, le=8000)

    @field_validator("api_base")
    @classmethod
    def plain_endpoint(cls, value):
        if value.username or value.password or value.query or value.fragment:
            raise ValueError("API 地址不能包含账号、密码、查询参数或片段")
        return value

    @field_validator("model")
    @classmethod
    def nonempty_model(cls, value):
        if not value.strip():
            raise ValueError("请填写模型名称")
        return value.strip()
