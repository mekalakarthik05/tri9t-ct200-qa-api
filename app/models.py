from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def now_utc(): return datetime.now(timezone.utc)

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, default="CardioTrack CT-200 Manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    versions: Mapped[list["DocumentVersion"]] = relationship(back_populates="document")

class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    source_filename: Mapped[str] = mapped_column(String)
    source_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    document: Mapped[Document] = relationship(back_populates="versions")
    nodes: Mapped[list["NodeVersion"]] = relationship(back_populates="version", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("document_id", "version_number"),)

class LogicalNode(Base):
    __tablename__ = "logical_nodes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

class NodeVersion(Base):
    __tablename__ = "node_versions"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # immutable version-specific node ID
    logical_node_id: Mapped[str] = mapped_column(ForeignKey("logical_nodes.id"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), index=True)
    parent_node_id: Mapped[str | None] = mapped_column(ForeignKey("node_versions.id"), nullable=True)
    heading: Mapped[str] = mapped_column(Text)
    level: Mapped[int] = mapped_column(Integer)
    body_text: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    structure_warnings: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[DocumentVersion] = relationship(back_populates="nodes")

class Selection(Base):
    __tablename__ = "selections"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    document_id: Mapped[str] = mapped_column(String, index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    items: Mapped[list] = mapped_column(JSON)  # immutable node-version IDs and hashes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
