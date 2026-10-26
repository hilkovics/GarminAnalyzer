"""Block progress of the coach "Kondícia" (METRICS §11.4): glue only, `training.planning_block` decides."""

import datetime as dt
from dataclasses import asdict

from sqlalchemy import select
from sqlmodel import Session

from training import planning, planning_block, planning_fitness
from training.coach import block_progress as bp, fitness
from training.db.models import CoachBlock
from training.services.dto import (
    BlockProgressDTO,
    BlockRefDTO,
    BlockSummaryDTO,
    BlockWeekDTO,
    CheckRunDTO,
    FitnessChangeDTO,
    FitnessSnapshotDTO,
)
from training.services.errors import NotFoundError


def _end(block: CoachBlock) -> dt.date:
    return block.start_monday + dt.timedelta(weeks=fitness.BLOCK_WEEKS, days=-1)


def _snapshot(value: bp.Snapshot) -> FitnessSnapshotDTO:
    return FitnessSnapshotDTO(**asdict(value), stale=value.stale)


def _change(value: bp.Change | None) -> FitnessChangeDTO | None:
    return FitnessChangeDTO(**asdict(value)) if value is not None else None


def list_blocks(session: Session, *, today: dt.date) -> list[BlockRefDTO]:
    return [
        BlockRefDTO(start=b.start_monday, end=_end(b), current=b.start_monday <= today <= _end(b))
        for b in planning_block.blocks(session)
    ]


def get_block(session: Session, *, today: dt.date, start: dt.date | None = None) -> BlockProgressDTO | None:
    """The block starting `start`, else the one containing today, else the latest; None without blocks."""
    if start is not None:
        block = session.execute(select(CoachBlock).where(CoachBlock.start_monday == start)).scalar()
        if block is None:
            raise NotFoundError(f"no coach block starts on {start}")
    else:
        if planning.mode_for(session, today) == "fitness":  # this week's row (never in race mode)
            planning_fitness.existing_week(session, planning_fitness.monday_of(today), today)
        blocks = planning_block.blocks(session)
        current = [b for b in blocks if b.start_monday <= today <= _end(b)]
        block = current[0] if current else (blocks[0] if blocks else None)
        if block is None:
            return None
    result = planning_block.progress(session, block, today)
    return BlockProgressDTO(
        start=block.start_monday,
        end=_end(block),
        block_weeks=fitness.BLOCK_WEEKS,
        baseline=_snapshot(result.baseline),
        weeks=[
            BlockWeekDTO(
                **{k: v for k, v in asdict(w).items() if k != "value"},
                value=_snapshot(w.value),
                change=_change(bp.change(result.baseline, w.value)),
            )
            for w in result.weeks
        ],
        check_runs=[
            CheckRunDTO(date=c.day, **{k: v for k, v in asdict(c).items() if k != "day"})
            for c in result.check_runs
        ],
        summary=BlockSummaryDTO(
            **{k: v for k, v in asdict(result.summary).items() if k != "change"},
            change=_change(result.summary.change),
        ),
    )
