"一次同步的完整流水。"

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any

from app.core.config import settings
from app.core.crypto import decrypt_secret
from app.core.db import SessionLocal
from app.core.mask import mask_text
from app.models.app import DdApp
from app.models.datasource import DdDatasource
from app.models.doc import DdDoc
from app.models.run import (
    RUN_FAILED,
    RUN_RUNNING,
    RUN_SUCCESS,
    DdRun,
    DdRunIssue,
    DdRunLog,
)
from app.models.task import DdTask
from app.services.loader import ddl as ddl_mod
from app.services.loader import dsn as dsn_mod
from app.services.loader import reconcile
from app.services.loader import writer as writer_mod
from app.services.loader.ddl import ensure_table
from app.services.loader.dialects import dialect_for
from app.services.normalize.coercions import to_datetime
from app.services.runner.logbus import RunLogger, hub
from app.services.runner.prepare import (
    DEFAULT_DIRTY_COLUMN,
    DEFAULT_SOURCE_TAG,
    MappingError,
    build_specs,
    prepare_rows,
)
from app.services.runner.safety import assess_write_safety, run_status
from app.services.schedule_rules import next_after

logger = logging.getLogger(__name__)

from app.services.normalize.mapping import ColumnSpec as ColumnSpec  # noqa: E402
from app.services.sheet_meta import load_sheet_meta  # noqa: E402
from app.services.sheet_meta import remember_sheet_columns as _remember_sheet_columns  # noqa: E402
from app.services.sources import build_source  # noqa: E402
from app.services.sources.base import RunAborted as RunAborted  # noqa: E402
from app.services.sources.base import SourceError  # noqa: E402
from app.services.sources.data import MAX_ROWS as MAX_ROWS  # noqa: E402
from app.services.sources.data import SourceData as SourceData  # noqa: E402
from app.services.tabular.align import (  # noqa: E402
    missing_expected_headers as missing_expected_headers,
)


def safe_run_error(exc: Exception) -> str:
    """数据库异常常带整批参数，不能原样存进执行记录或回显。"""
    from sqlalchemy.exc import SQLAlchemyError

    if isinstance(exc, SQLAlchemyError):
        return f"数据库写入失败（{type(exc).__name__}）。请检查目标表列类型、约束和执行日志。"
    return mask_text(f"{type(exc).__name__}: {exc}")[:500]


def _apply_incremental(
    rows: list[dict[str, Any]], *, source_cfg: dict[str, Any], logger: RunLogger
) -> list[dict[str, Any]]:
    "增量窗口：只看某个日期列最近 N 天的行。"
    cfg = (source_cfg or {}).get("incremental") or {}
    column = str(cfg.get("column") or "").strip()
    days = int(cfg.get("days") or 0)
    if not column or not days or not rows:
        return rows

    sample = rows[0] or {}
    if column not in sample:
        logger.warn(
            f"增量列「{column}」不在写入的列里，这次不做增量过滤。"
            f"可选的列：{'、'.join(list(sample)[:10])}"
        )
        return rows

    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    kept: list[dict[str, Any]] = []
    dropped = 0
    for row in rows:
        value = row.get(column)
        if value is None:
            kept.append(row)
            continue
        if isinstance(value, dt.datetime):
            moment = value
        elif isinstance(value, dt.date):
            moment = dt.datetime(value.year, value.month, value.day)
        else:
            try:
                moment = to_datetime(value)
            except Exception:  # noqa: BLE001 — 认不出的日期就当它该保留，交给列映射去报错
                kept.append(row)
                continue
        if moment is not None and moment < cutoff:
            dropped += 1
            continue
        kept.append(row)

    logger.info(f"增量窗口：只看「{column}」最近 {days} 天，过滤掉 {dropped} 行（剩 {len(kept)} 行）")
    return kept


def _pk_text(value: Any) -> str:
    "主键值得比成一串文本再比。"
    return "" if value is None else str(value).strip()


def _type_advice(
    column: str, header_index: dict[str, int], source: SourceData, specs: list[ColumnSpec]
) -> str:
    "转不了的时候，顺手告诉他这列实际看着像什么类型。"
    from app.models.task import COL_TYPE_LABELS
    from app.services.normalize.coercions import infer_type

    index = header_index.get(column)
    if index is None:
        return ""
    configured = next((s.type for s in specs if s.target == column), "")
    samples = [row[1][index] if index < len(row[1]) else None for row in source.rows]
    better = infer_type(samples)
    if not better or better == configured:
        return " —— 去第 2 步把这一列的类型改一下"
    label = COL_TYPE_LABELS.get(better, better)
    current = COL_TYPE_LABELS.get(configured, configured)
    return f" —— 这列实际看着像「{label}」，当前配的是「{current}」，建议改过来"


async def _save_logs(run: DdRun, logger: RunLogger) -> None:
    if not logger.lines:
        return
    async with SessionLocal() as session:
        for index, (level, content) in enumerate(logger.lines):
            session.add(
                DdRunLog(
                    run_id=run.id,
                    seq=index,
                    stream="stderr" if level in ("warn", "error") else "stdout",
                    content=content,
                )
            )
        await session.commit()


async def _finish(
    run_id: int,
    *,
    status: str,
    stats: writer_mod.WriteStats | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    summary: dict[str, Any] | None = None,
) -> None:
    async with SessionLocal() as session:
        run = await session.get(DdRun, run_id)
        if run is None:
            return
        now = dt.datetime.now()
        run.status = status
        run.finished_at = now
        if run.started_at:
            run.duration_ms = int((now - run.started_at).total_seconds() * 1000)
        if stats is not None:
            run.rows_read = stats.read
            run.rows_written = stats.written
            run.rows_inserted = stats.inserted
            run.rows_updated = stats.updated
            run.rows_unchanged = stats.unchanged
            run.rows_failed = stats.failed
            run.batches = stats.batches
        if error_type:
            run.error_type = error_type
        if error_message:
            run.error_message = error_message
        if summary:
            run.stats = {**(run.stats or {}), **summary}

        task = await session.get(DdTask, run.task_id)
        is_dry = bool(run.dry_run)
        if task is not None:
            if not is_dry:
                task.last_run_at = now
                task.last_run_status = status
                if status == RUN_SUCCESS:
                    task.last_success_at = now
                task.last_summary = summary or {}
            task.next_run_at = next_after(task.schedule, now)
        await session.commit()

    try:
        from app.services.actions import run_post_actions

        await run_post_actions(run_id, dry_run=is_dry)
    except Exception:  # noqa: BLE001 — 动作怎么炸都不能影响已经成功的同步
        logger.exception("后置动作整体异常（不影响同步结果）")


async def _record_issues(run_id: int, issues: list[dict[str, Any]]) -> None:
    if not issues:
        return
    async with SessionLocal() as session:
        for item in issues[: settings.run_issue_max_rows]:
            session.add(
                DdRunIssue(
                    run_id=run_id,
                    row_no=item.get("row_no"),
                    column=item.get("column"),
                    reason=str(item.get("reason") or "")[:255],
                    raw=item.get("raw"),
                )
            )
        await session.commit()


async def execute_run(run_id: int, *, dry_run: bool = False, row_limit: int | None = None) -> None:
    logger = RunLogger(run_id)
    stats = writer_mod.WriteStats()
    issues: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}

    try:
        async with SessionLocal() as session:
            run = await session.get(DdRun, run_id)
            if run is None:
                logger.error("执行记录不存在")
                return
            task = await session.get(DdTask, run.task_id)
            if task is None:
                raise RunAborted("任务已被删除")
            doc = await session.get(DdDoc, task.doc_id)
            if doc is None:
                raise RunAborted("任务关联的文档已被删除")
            app = await session.get(DdApp, doc.app_id)
            if app is None:
                raise RunAborted("文档关联的钉钉应用已被删除")

            run.status = RUN_RUNNING
            run.started_at = dt.datetime.now()
            run.dry_run = dry_run
            run.row_limit = row_limit
            summary = {
                "task": task.name,
                "doc": doc.name,
                "sheet": task.sheet_name or task.sheet_id,
                "table": task.target_table,
                "dry_run": dry_run,
            }
            await session.commit()

            secret = str(decrypt_secret(app.app_secret_enc).get("app_secret") or "")

            meta = await load_sheet_meta(session, doc.id)
            names, history = meta.names, meta.history

        logger.info(f"开始同步：{summary['doc']} / {summary['sheet']} → {summary['table']}")
        if dry_run:
            logger.info(f"这是试跑，只读不写；最多读 {row_limit or '全部'} 行")

        await _check_cancel(run_id)

        source = await build_source(app, doc, secret=secret).read(
            task, doc, logger, names=names, history=history, limit=row_limit
        )

        await _remember_sheet_columns(doc.id, source.sheet_columns, source.sheet_column_types)

        stats.read = len(source.rows)
        logger.info(f"读到 {stats.read} 行有效数据")
        if source.skipped_formula_cells:
            summary["skipped_formula_cells"] = source.skipped_formula_cells
            issues.append(
                {
                    "column": "数值",
                    "reason": f"源表公式错误，已跳过 {source.skipped_formula_cells} 个单元格；详情见日志",
                    "row_no": None,
                }
            )
        if not source.rows:
            logger.warn("没有读到任何数据，任务结束")
            await _finish(run_id, status=RUN_SUCCESS, stats=stats, summary=summary)
            return

        target = task.target or {}
        ds_id = target.get("datasource_id")
        if not ds_id:
            raise RunAborted("任务还没选目标库")
        async with SessionLocal() as session:
            ds = await session.get(DdDatasource, int(ds_id))
            if ds is None:
                raise RunAborted("目标库已被删除")
            ds_kwargs = {
                "db_type": ds.db_type,
                "host": ds.host,
                "port": ds.port,
                "database": ds.database,
                "username": ds.username,
                "password": str(decrypt_secret(ds.password_enc).get("password") or ""),
                "extra": ds.extra,
            }

        table = task.target_table
        if not table:
            raise RunAborted("任务还没配目标表名")

        target_types = await asyncio.to_thread(_probe_target_types, ds_kwargs, table, logger)

        specs = build_specs(task.columns)
        from app.services.normalize.rowfilter import skip_config

        skip_rows_cfg, skip_words_cfg = skip_config(task.source_config)
        try:
            prepared = prepare_rows(
                source,
                specs,
                dedupe_cfg=task.dedupe or {},
                tag_cfg=(task.target or {}).get("source_tag") or {},
                doc_node_id=doc.node_id,
                sheet_id=task.sheet_id,
                now=dt.datetime.now(),
                max_issues=settings.run_issue_max_rows,
                target_types=target_types,
                dirty_column=(task.target or {}).get("dirty_column", None)
                if "dirty_column" in (task.target or {})
                else DEFAULT_DIRTY_COLUMN,
                quality_block_columns=list(
                    dict.fromkeys(
                        list(target.get("quality_block_columns") or [])
                        + list(target.get("key_columns") or [])
                        + ([target.get("partition_column")] if target.get("partition_column") else [])
                    )
                ),
                numeric_note_columns=list(target.get("numeric_note_columns") or []),
                note_column=str(target.get("note_column") or "备注"),
                split_by=(task.source_config or {}).get("split_columns") or None,
                skip_rows=skip_rows_cfg,
                skip_words=skip_words_cfg,
                rules_cfg=(task.source_config or {}).get("rules"),
            )
        except MappingError as exc:
            raise RunAborted(str(exc)) from exc

        if prepared.dropped_rows:
            logger.warn(
                f"按「小计/合计/说明行」跳过了 {len(prepared.dropped_rows)} 行："
                + "；".join(prepared.dropped_rows[:6])
                + ("…" if len(prepared.dropped_rows) > 6 else "")
                + "（如果不该跳，回到第 2 步改「跳过哪些行」）"
            )

        if prepared.auto_split:
            logger.info(
                "自动识别出「一个格子里写了多个值」的列，已展开成多行："
                + "；".join(f"{name}（按「{sep}」拆）" for name, sep in prepared.auto_split.items())
                + "。展开之后记录数会变多，那是正常的。"
            )

        if prepared.rule_notes:
            logger.info(
                f"按规则改了 {len(prepared.rule_notes)} 处："
                + "；".join(prepared.rule_notes[:6])
                + ("…" if len(prepared.rule_notes) > 6 else "")
            )

        issues.extend(prepared.issues)
        stats.failed += prepared.skipped_required
        quality = {
            "invalid_rows": prepared.bad_rows,
            "invalid_cells": prepared.invalid_cells,
            "critical_cells": prepared.critical_cells,
            "skipped_rows": prepared.skipped_required,
            "adjusted_columns": len(prepared.retyped_columns),
            "original_retained": bool(prepared.dirty_column),
            "repaired_dates": len(prepared.repaired_dates),
            "amount_notes": prepared.amount_notes,
            "skipped_formula_cells": source.skipped_formula_cells,
        }
        summary["quality"] = quality
        logger.info(f"字段映射 {len(specs)} 列，可写入 {len(prepared.rows)} 行")
        if prepared.repaired_dates:
            logger.info(f"已按同一子表相邻日期补全 {len(prepared.repaired_dates)} 个简写日期，写回测评日期列")
        if prepared.amount_notes:
            logger.info(
                f"已把 {prepared.amount_notes} 个金额说明转入"
                f"「{target.get('note_column') or '备注'}」，原金额写 0"
            )
        if prepared.invalid_cells:
            logger.warn(
                f"数据质量：{prepared.bad_rows} 行、{prepared.invalid_cells} 个异常格；"
                f"其中 {prepared.critical_cells} 个涉及关键列"
            )
        if prepared.issue_summary:
            logger.warn(f"{prepared.bad_rows} 行有问题，按列汇总：")
            header_index = {name: i for i, name in enumerate(source.header)}
            for item in prepared.issue_summary[:10]:
                sample = item.get("samples") or []
                example = f"（例如 {sample[0]}）" if sample else ""
                logger.warn(
                    f"  「{item['column']}」{item['rows']} 行：{item['reason']}{example}"
                    + _type_advice(item["column"], header_index, source, specs)
                )
            if len(prepared.issue_summary) > 10:
                logger.warn(f"  …… 还有 {len(prepared.issue_summary) - 10} 列有问题")
        if prepared.deduped:
            logger.info(f"去重去掉 {prepared.deduped} 条")
        if prepared.retyped_columns:
            _log_retyped(logger, prepared.retyped_columns)
        if prepared.blocked_values:
            _log_blocked_values(logger, prepared.blocked_values, prepared.dirty_column)
            for item in prepared.blocked_values:
                issues.append(
                    {
                        "column": item["column"],
                        "reason": f"{item['count']} 个值装不下，已移到「{prepared.dirty_column}」",
                        "row_no": None,
                    }
                )
        if prepared.critical_cells or (prepared.invalid_cells and not prepared.dirty_column):
            await _record_issues(run_id, issues)
            if prepared.critical_issues:
                first = prepared.critical_issues[0]
                location = f"第 {first['row_no']} 行" if first["row_no"] else "源记录"
                raise RunAborted(
                    f"关键列「{first['column']}」在{location}有异常；"
                    f"共 {prepared.critical_cells} 个关键格未通过，已停止写入"
                )
            raise RunAborted("异常原文保留列已关闭，存在无法转换的值；已停止写入")
        if not prepared.rows:
            logger.warn("归一化之后没有可写入的行")

        mapped_rows = _apply_incremental(prepared.rows, source_cfg=task.source_config or {}, logger=logger)
        if not mapped_rows:
            logger.warn("增量窗口过滤之后没有可写入的行")

        all_columns = prepared.columns
        fingerprint_column = prepared.fingerprint_column
        insert_only = prepared.insert_only
        logger.info("目标列：" + "、".join(all_columns))

        write_mode = str(target.get("write_mode") or writer_mod.WRITE_UPSERT)
        key_columns = list(target.get("key_columns") or [])
        if write_mode == writer_mod.WRITE_UPSERT and not key_columns:
            raise RunAborted("按主键更新需要先指定主键列")

        logger.info(f"目标表：{table}（{write_mode}）")

        if key_columns and write_mode == writer_mod.WRITE_UPSERT and mapped_rows:
            seen: dict[tuple, int] = {}
            for row in mapped_rows:
                stamp = tuple(_pk_text(row.get(c)) for c in key_columns)
                seen[stamp] = seen.get(stamp, 0) + 1
            dupes = sorted(((k, n) for k, n in seen.items() if n > 1), key=lambda kv: kv[1], reverse=True)
            if dupes:
                hit = sum(n for _, n in dupes)
                logger.warn(
                    f"⚠ 主键重复：{len(dupes)} 组、涉及 {hit} 行。"
                    f"这 {hit} 行里只有最后一条能进目标表，其余会被丢掉 ——"
                    "而且这个任务从第二次跑开始会被数据库直接拒绝。"
                )
                for keys, count in dupes[:8]:
                    logger.warn(
                        "  "
                        + " | ".join(
                            f"{name}={value}" for name, value in zip(key_columns, keys, strict=False)
                        )
                        + f"  →  {count} 行（只留最后一条）"
                    )
                if len(dupes) > 8:
                    logger.warn(f"  …… 还有 {len(dupes) - 8} 组")
                logger.warn(
                    "  怎么办：这几列合起来不足以区分每一行，需要再挑一列加进主键"
                    "（比如费用细分、明细编号这种每行不同的），或者把「源里没有的怎么办」"
                    "配成整表重写。加列之前先确认加上去真的不重了。"
                )

        await _check_cancel(run_id)

        column_types = dict(prepared.effective_types)
        for name in all_columns:
            column_types.setdefault(name, "text")

        tag = {**DEFAULT_SOURCE_TAG, **(target.get("source_tag") or {})}
        scope_column = (tag.get("sheet") or "").strip() or None
        scope_value = task.sheet_id if scope_column else None
        on_missing = str(target.get("on_missing") or reconcile.ON_MISSING_KEEP)
        if source.skipped_formula_cells and on_missing != reconcile.ON_MISSING_KEEP:
            logger.warn("源表有公式错误，本次不处理目标表中缺失的记录，避免误删或误标记")
            on_missing = reconcile.ON_MISSING_KEEP
        mark_column = str(target.get("deleted_flag_column") or "__is_deleted__")
        incremental_cfg = (task.source_config or {}).get("incremental") or {}
        incremental_active = bool(incremental_cfg.get("column") and incremental_cfg.get("days"))
        incomplete_source = bool(
            row_limit
            or incremental_active
            or prepared.skipped_required
            or len(source.rows) >= MAX_ROWS
            or not mapped_rows
            or source.skipped_formula_cells
        )
        prior_rows = (
            await asyncio.to_thread(_count_existing_target_rows, ds_kwargs, table)
            if write_mode == writer_mod.WRITE_FULL_REPLACE
            else None
        )
        ratio_value = target.get("minimum_row_ratio")
        safety = assess_write_safety(
            mode=write_mode,
            source_rows=len(source.rows),
            output_rows=len(mapped_rows),
            previous_rows=prior_rows,
            row_limited=bool(row_limit),
            incremental=incremental_active,
            source_cap_reached=len(source.rows) >= MAX_ROWS,
            skipped_required=prepared.skipped_required,
            critical_cells=prepared.critical_cells,
            retyped_columns=len(prepared.retyped_columns),
            minimum_row_ratio=0.5 if ratio_value is None else float(ratio_value),
        )
        summary["safety"] = {
            "can_write": safety.can_write,
            "blockers": list(safety.blockers),
            "previous_rows": safety.previous_rows,
        }
        if safety.blockers:
            for reason in safety.blockers:
                logger.warn(f"覆盖写入保护：{reason}")
            if not dry_run:
                raise RunAborted("覆盖写入已拦截：" + "；".join(safety.blockers))
        if on_missing != reconcile.ON_MISSING_KEEP and key_columns and scope_column and incomplete_source:
            raise RunAborted(
                "当前读取的不是完整源表（限行、增量、缺失必填行或达到行数上限），"
                "已停止删除对账，避免误删目标表数据"
            )

        table_state: list[dict[str, Any]] = []

        def _do_write() -> tuple[writer_mod.WriteStats, int, reconcile.ReconcileResult]:
            engine = dsn_mod.make_engine(**ds_kwargs)
            try:
                db_dialect = dialect_for(ds_kwargs["db_type"])
                column_defs = {name: column_types.get(name, "text") for name in all_columns}
                table_missing = False

                if target.get("auto_create", True):
                    if dry_run:
                        with engine.connect() as conn:
                            existing = ddl_mod.existing_columns(conn, db_dialect, table)
                            plan = ddl_mod.plan_table(
                                db_dialect,
                                table,
                                column_defs,
                                existing=existing,
                            )

                            widen = ddl_mod.plan_widen_columns(
                                db_dialect, table, column_defs, existing=existing
                            )
                        for statement in plan.statements + widen:
                            logger.info(f"试跑（没执行）：正式跑时会做这个结构调整 —— {statement}")

                        table_missing = bool(plan.will_create)
                    else:
                        with engine.begin() as conn:
                            plan = ensure_table(conn, db_dialect, table, column_defs)

                            for stmt in ddl_mod.plan_widen_columns(
                                db_dialect,
                                table,
                                column_defs,
                                existing=ddl_mod.existing_columns(conn, db_dialect, table),
                            ):
                                from sqlalchemy import text as _text

                                conn.execute(_text(stmt))

                                plan.statements.append(stmt)

                            before_rows = (
                                None if plan.will_create else ddl_mod.count_rows(conn, db_dialect, table)
                            )
                        for statement in plan.statements:
                            logger.info(f"结构变更：{statement}")
                        if write_mode == writer_mod.WRITE_FULL_REPLACE:
                            if plan.will_create:
                                logger.info("目标表是这次新建的，本次所有行都应该是「新增」")
                            elif before_rows:
                                logger.info(
                                    f"整表重写会先清空里面原有的 {before_rows} 行"
                                    + ("以上" if before_rows > ddl_mod.COUNT_CAP else "")
                                    + "，再把这次读到的全部写进去 —— 结果只会是「新增」"
                                )
                            else:
                                logger.info("目标表已存在但是空的，本次所有行都应该是「新增」")
                        elif plan.will_create:
                            logger.info("目标表是这次新建的，所以本次所有行都应该是「新增」")
                        elif before_rows:
                            logger.info(
                                f"目标表是**已经存在**的，里面原有 {before_rows} 行"
                                + ("以上" if before_rows > ddl_mod.COUNT_CAP else "")
                                + " —— 所以会出现「更新」和「未变」，那是上次跑留下的数据"
                            )
                        elif before_rows == 0:
                            logger.info("目标表已存在但是空的，本次所有行都应该是「新增」")
                        table_state.append(
                            {
                                "table_created": bool(plan.will_create),
                                "rows_before": before_rows,
                            }
                        )

                if dry_run:
                    if table_missing:
                        count = 0
                    else:
                        with engine.connect() as conn:
                            count = ddl_mod.count_rows(conn, db_dialect, table)
                    table_state.append({"table_created": count == 0, "rows_before": count})
                    diff = (
                        reconcile.ReconcileResult(to_insert=len(mapped_rows))
                        if table_missing
                        else reconcile.preview_diff(
                            engine,
                            table=table,
                            key_columns=key_columns,
                            rows=mapped_rows,
                            fingerprint_column=fingerprint_column,
                            scope_column=scope_column,
                            scope_value=scope_value,
                        )
                    )
                    return writer_mod.WriteStats(read=len(mapped_rows)), 0, diff

                with engine.connect() as conn:
                    conflicts = ddl_mod.find_type_conflicts(
                        column_types, ddl_mod.existing_columns(conn, db_dialect, table)
                    )
                if conflicts:
                    _log_type_conflicts(logger, conflicts, prepared)
                    raise RunAborted("目标表里的列类型装不下这些值，先把上面列出的格子改掉再跑")

                cleaned = [0]

                def _after_write(conn) -> None:
                    if on_missing == reconcile.ON_MISSING_KEEP or not key_columns or not scope_column:
                        return
                    keep = {tuple(row.get(c) for c in key_columns) for row in mapped_rows}
                    cleaned[0] = reconcile.apply_missing(
                        engine,
                        table=table,
                        key_columns=key_columns,
                        scope_column=scope_column,
                        scope_value=scope_value,
                        keep_keys=keep,
                        mode=on_missing,
                        mark_column=mark_column,
                        connection=conn,
                    )

                result = writer_mod.write(
                    engine,
                    table=table,
                    columns=all_columns,
                    rows=mapped_rows,
                    mode=write_mode,
                    key_columns=key_columns,
                    partition_column=target.get("partition_column"),
                    fingerprint_column=fingerprint_column,
                    insert_only_columns=insert_only,
                    batch_size=settings.load_batch_size,
                    after_write=_after_write,
                )
                return result, cleaned[0], reconcile.ReconcileResult()

            finally:
                engine.dispose()

        result, cleaned, diff = await asyncio.to_thread(_do_write)

        if dry_run:
            before_rows = (table_state[0].get("rows_before") if table_state else 0) or 0
            if write_mode == writer_mod.WRITE_FULL_REPLACE:
                logger.info(
                    f"试跑对比：整表重写会把 {table} 先清空，"
                    f"再把这次读到的 {len(mapped_rows)} 行全部写进去。"
                    "不做「新增 / 更新 / 不变」的比较 —— 整表重写不比较主键。"
                )
                if before_rows:
                    logger.warn(
                        f"⚠ 现在表里有 {before_rows} 行"
                        + ("以上" if before_rows > ddl_mod.COUNT_CAP else "")
                        + "，正式跑之后只剩下这次写入的行数。"
                        "确认这张表没有别的任务或别的系统在写。"
                    )
            elif key_columns:
                logger.info(
                    f"试跑对比（按 {'、'.join(key_columns)} 跟目标表比）："
                    f"会新增 {diff.to_insert} 行、更新 {diff.to_update} 行、"
                    f"不变 {diff.unchanged} 行"
                )
                if on_missing != reconcile.ON_MISSING_KEEP:
                    logger.info(
                        f"另外有 {diff.missing} 行在源里已经没有了，正式跑时会"
                        f"{reconcile.ON_MISSING_LABELS.get(on_missing, on_missing)}"
                    )
                elif diff.missing:
                    logger.info(
                        f"另外有 {diff.missing} 行在源里已经没有了 —— 当前设置是「不动」，"
                        "它们会一直留在目标表里。想清掉就把「源里没有的怎么办」改成删除或标记。"
                    )
            else:
                logger.info("没设主键列，没法跟目标表对比；只能看出共读到多少行")
            logger.info("这是试跑，没有写任何数据")
            await _record_issues(run_id, issues)
            await _save_logs(run, logger)
            await _finish(
                run_id,
                status=run_status(
                    failed_rows=0,
                    retyped_columns=len(prepared.retyped_columns),
                    blockers=safety.blockers,
                ),
                stats=writer_mod.WriteStats(read=len(mapped_rows)),
                summary={
                    **summary,
                    "dry_run": True,
                    "will_insert": diff.to_insert,
                    "will_update": diff.to_update,
                    "unchanged": diff.unchanged,
                    "missing": diff.missing,
                },
            )
            logger.info("任务结束")
            return

        stats.merge(result)
        if cleaned:
            logger.info(
                f"源里已经没有的 {cleaned} 行，已"
                f"{'标记为删除' if on_missing == reconcile.ON_MISSING_MARK else '从目标表删除'}"
            )

        logger.info(
            f"写入完成：新增 {stats.inserted}，更新 {stats.updated}，"
            f"未变化 {stats.unchanged}，失败 {stats.failed}，共 {stats.batches} 批"
        )
        if stats.duplicates:
            logger.warn(
                f"⚠ 源里有 {stats.duplicates} 行主键重复，已按「最后一条为准」合并写入。"
                f"写进去 {stats.written} 行，不是读到的 {stats.read} 行。"
            )
            logger.warn(
                "  注意：被合并掉的不一定是脏数据 —— 完全可能是「同一天同一类费用"
                "真的发生了好几笔，金额恰好也一样」。数据库分不清这两种情况。"
            )
            logger.warn(
                "  两种改法：① 在源表里加一列「明细编号」（每行不同），把它加进主键；"
                "② 写入方式改成「整表重写」—— 那样不比较主键，每一行都会写进去。"
            )

        fresh_table = bool(
            table_state and (table_state[0].get("table_created") or table_state[0].get("rows_before") == 0)
        )
        if fresh_table and (stats.updated or stats.unchanged):
            dup = stats.updated + stats.unchanged
            logger.warn(
                f"目标表本来是空的，却有 {dup} 行被算成「更新/未变」—— "
                f"多半是源里有 {dup} 行的主键（{'、'.join(key_columns)}）跟别的行重复。"
                "重复的行会被后一条覆盖掉，想留住每一行就换一组主键列，或者用「只追加」策略。"
            )
            issues.append(
                {
                    "column": "、".join(key_columns),
                    "reason": f"源里主键重复 {dup} 行（后一条覆盖前一条）",
                    "row_no": None,
                }
            )
        await _record_issues(run_id, issues)
        await _save_logs(run, logger)

        status = run_status(
            failed_rows=stats.failed,
            retyped_columns=len(prepared.retyped_columns),
        )
        await _finish(
            run_id,
            status=status,
            stats=stats,
            summary={
                **summary,
                "inserted": stats.inserted,
                "updated": stats.updated,
                "unchanged": stats.unchanged,
                "failed": stats.failed,
                "removed": cleaned,
                **(table_state[0] if table_state else {}),
            },
        )
        logger.info("任务结束")

    except RunAborted as exc:
        logger.error(str(exc))
        await _save_logs_quiet(run_id, logger)
        await _finish(
            run_id,
            status=RUN_FAILED,
            stats=stats,
            error_type="Aborted",
            error_message=mask_text(str(exc))[:500],
            summary=summary,
        )
    except SourceError as exc:
        logger.error(f"读源失败：{exc}")
        if exc.hint:
            logger.error(f"怎么办：{exc.hint}")
        await _save_logs_quiet(run_id, logger)
        await _finish(
            run_id,
            status=RUN_FAILED,
            stats=stats,
            error_type=exc.code or "SourceError",
            error_message=mask_text(str(exc))[:500],
            summary=summary,
        )
    except Exception as exc:  # noqa: BLE001 — 兜底：任何意外都要落账，不能让 run 卡在「运行中」
        safe_message = safe_run_error(exc)
        logger.error(f"执行失败：{safe_message}")
        await _save_logs_quiet(run_id, logger)
        await _finish(
            run_id,
            status=RUN_FAILED,
            stats=stats,
            error_type=type(exc).__name__,
            error_message=safe_message,
            summary=summary,
        )
    finally:
        logger.close()
        hub.close(run_id)


def _log_type_conflicts(logger: RunLogger, conflicts: list[dict[str, str]], prepared: Any) -> None:
    "把「目标列是数字、但要写进去的是文本」说清楚。"

    by_column = {a["column"]: a for a in getattr(prepared, "auto_adjustments", [])}
    logger.warn(
        f"⚠ 有 {len(conflicts)} 列对不上，正式写入会被数据库拒绝："
        "源里这些列混进了没法当数字/日期用的值，平台把它们放宽成了文本，"
        "但目标表的列还是数字/日期类型。"
    )
    for item in conflicts:
        adj = by_column.get(item["column"], {})
        samples = "、".join(adj.get("samples") or []) or "（见上面的坏行）"
        logger.warn(
            f"  「{item['column']}」目标库是 {item['existing'].upper()}，"
            f"但源里有 {adj.get('count', '?')} 个值不是数字 —— 例如 {samples}"
        )
    logger.warn(
        "  怎么办：① 去源文档把那些格子改成干净的数字（最常见的是两行内容黏在一格里）；"
        "② 或者把这一列的类型改成「文本」，然后手动把目标库那一列也改成 NVARCHAR。"
    )


def _log_blocked_values(logger: RunLogger, blocked: list[dict[str, Any]], dirty_column: str | None) -> None:
    "哪些格子装不下、已经搬到「未识别」列了。"
    from app.models.task import COL_TYPE_LABELS

    total = sum(int(i["count"]) for i in blocked)
    where = f"「{dirty_column}」列" if dirty_column else "（没配脏数据列，原始值已丢弃）"
    logger.warn(f"{len(blocked)} 列里有 {total} 个格子填得不对，原文已挪到 {where}：")
    for item in blocked:
        samples = "、".join(item.get("samples") or [])
        label = COL_TYPE_LABELS.get(item["used"], item["used"])
        logger.warn(f"  「{item['column']}」{item['count']} 个值不是{label} —— 例如 {samples}")
    if dirty_column:
        logger.warn(
            f"  数据没丢，都在「{dirty_column}」里（格式：列名=原文）。"
            f"想清理就在目标表里筛「{dirty_column}」不为空的行。"
        )


def _log_retyped(logger: RunLogger, retyped: list[dict[str, Any]]) -> None:
    "这几列的类型判断错了，平台已经自动换掉。"
    logger.warn(f"{len(retyped)} 列的类型自动调整了（原来的装不下大部分数据）：")
    for item in retyped:
        logger.warn(
            f"  「{item['column']}」原来按「{item['from_label']}」处理，"
            f"实际数据更像「{item['label']}」，已按「{item['label']}」写入"
        )
    logger.warn("  不用管，平台已处理。目标表那一列也会跟着放宽（只放宽、不收紧）。")


def _probe_target_types(ds_kwargs: dict[str, Any], table: str, logger: RunLogger) -> dict[str, str]:
    "探一下目标表**已经有哪些列、各是什么类型**。"
    if not table:
        return {}
    try:
        engine = dsn_mod.make_engine(**ds_kwargs)
    except Exception:  # noqa: BLE001 — 连不上时后面写入自然会报，这里不必抢先
        return {}
    try:
        db_dialect = dialect_for(ds_kwargs["db_type"])
        with engine.connect() as conn:
            existing = ddl_mod.existing_columns(conn, db_dialect, table)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"没读到目标表结构（{type(exc).__name__}），这次按配置的类型写")
        return {}
    finally:
        engine.dispose()

    return dict(existing or {})


def _count_existing_target_rows(ds_kwargs: dict[str, Any], table: str) -> int | None:
    """Read an exact baseline before a full replacement can clear the table."""
    from sqlalchemy import text

    engine = dsn_mod.make_engine(**ds_kwargs)
    try:
        db_dialect = dialect_for(ds_kwargs["db_type"])
        with engine.connect() as conn:
            if ddl_mod.existing_columns(conn, db_dialect, table) is None:
                return None
            return int(conn.execute(text(f"SELECT COUNT(*) FROM {db_dialect.quote(table)}")).scalar_one())
    finally:
        engine.dispose()


async def _save_logs_quiet(run_id: int, logger: RunLogger) -> None:
    try:
        from sqlalchemy import select as _select

        async with SessionLocal() as session:
            run = await session.scalar(_select(DdRun).where(DdRun.id == run_id))
            if run is not None:
                await _save_logs(run, logger)
    except Exception:  # noqa: BLE001 — 日志入库失败不该盖住原始错误
        pass


async def _check_cancel(run_id: int) -> None:
    async with SessionLocal() as session:
        run = await session.get(DdRun, run_id)
        if run is not None and run.cancel_requested:
            raise RunAborted("已被手动取消")
