from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    Date,
    JSON,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class ContestDB(Base):
    __tablename__ = "contests"

    id = Column(String, primary_key=True)
    platform = Column(String, nullable=False)
    title = Column(String, nullable=False)
    url = Column(String, nullable=False)
    organizer = Column(String, nullable=False)
    deadline = Column(Date, nullable=True)
    start_date = Column(Date, nullable=True)
    prize = Column(String, nullable=True)
    prize_amount = Column(Integer, nullable=True)
    eligibility_raw = Column(Text, nullable=False, default="")
    eligibility_tags = Column(JSON, nullable=False, default=list)
    submission_format = Column(String, nullable=True)
    category = Column(String, nullable=False, default="")
    description = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="접수중")
    d_day = Column(Integer, nullable=True)
    scraped_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # State machine fields
    state = Column(String, nullable=False, default="discovered")
    retry_count = Column(Integer, nullable=False, default=0)

    analyses = relationship("AnalysisDB", back_populates="contest", cascade="all, delete-orphan")
    artifacts = relationship("ArtifactDB", back_populates="contest", cascade="all, delete-orphan")
    transitions = relationship("StateTransitionDB", back_populates="contest", cascade="all, delete-orphan")


class AnalysisDB(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contest_id = Column(String, ForeignKey("contests.id"), nullable=False)
    contest_type = Column(String, nullable=False)
    difficulty = Column(String, nullable=False)
    is_eligible = Column(Boolean, nullable=False)
    eligibility_reason = Column(Text, nullable=False, default="")
    roi_score = Column(Float, nullable=False, default=0.0)
    roi_breakdown = Column(JSON, nullable=False, default=dict)
    required_deliverables = Column(JSON, nullable=False, default=list)
    suggested_approach = Column(Text, nullable=False, default="")
    relevant_public_data = Column(JSON, nullable=False, default=list)
    keywords = Column(JSON, nullable=False, default=list)
    ai_restriction = Column(String, nullable=True)
    analyzed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    contest = relationship("ContestDB", back_populates="analyses")


class ArtifactDB(Base):
    __tablename__ = "artifacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contest_id = Column(String, ForeignKey("contests.id"), nullable=False)
    report_type = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    markdown_path = Column(String, nullable=False)
    title = Column(String, nullable=False)
    sections = Column(JSON, nullable=False, default=list)
    data_sources = Column(JSON, nullable=False, default=list)
    visualizations = Column(JSON, nullable=False, default=list)
    word_count = Column(Integer, nullable=False, default=0)
    generated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    generation_duration_sec = Column(Float, nullable=False, default=0.0)

    contest = relationship("ContestDB", back_populates="artifacts")


class StateTransitionDB(Base):
    __tablename__ = "state_transitions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contest_id = Column(String, ForeignKey("contests.id"), nullable=False)
    from_state = Column(String, nullable=False)
    to_state = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    reason = Column(Text, nullable=True)

    contest = relationship("ContestDB", back_populates="transitions")
