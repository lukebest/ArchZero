"""Acceptance-metric provenance and the refusal to grade off-domain specs.

The regression these guard against: a well-formed NoC / wafer-scale problem
package used to parse to the *same* four cache thresholds as the cache demo
(>=15% MPKI, <=5% DRAM bandwidth, <=0.5 mm²) with nothing marking three of
them as invented, so the funnel graded an interconnect study as a prefetcher.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from archzero.config import ROOT
from archzero.spec.acc_parse import (
    GATE_FIELDS,
    PERFORMANCE_GATES,
    parse_acceptance_thresholds,
)
from archzero.spec.lint import lint_acceptance, lint_package
from archzero.spec.metrics import (
    DOMAINS,
    METRIC_BY_ID,
    METRIC_SPECS,
    detect_metrics,
    infer_domain,
    metrics_for_domain,
)
from archzero.spec.ndf import load_problem_package
from archzero.spec.wizard import TEMPLATES, scaffold_problem, scaffold_unmeasurable_probe

SPECS = ROOT / "specs"


def _load(name: str):
    return load_problem_package(SPECS / f"{name}.md")


# --- registry ----------------------------------------------------------------


def test_registry_ids_unique_and_well_formed():
    ids = [m.id for m in METRIC_SPECS]
    assert len(ids) == len(set(ids))
    for m in METRIC_SPECS:
        assert m.domain in DOMAINS, m.id
        assert m.direction in {"lower_is_better", "higher_is_better"}, m.id
        assert m.aliases, m.id
        # An unmeasurable metric must say why, so `archzero acc` can explain it.
        if not m.measurable:
            assert m.note, m.id


def test_every_gate_field_maps_to_a_registered_metric():
    for gate_field, metric_id in GATE_FIELDS.items():
        assert metric_id in METRIC_BY_ID, gate_field
        assert METRIC_BY_ID[metric_id].measurable, metric_id


def test_metrics_for_domain_includes_generic():
    noc = metrics_for_domain("noc")
    assert any(m.id == "p99_latency" for m in noc)
    assert any(m.id == "magic_gap" for m in noc), "generic metrics apply everywhere"
    assert not any(m.id == "miss_reduction" for m in noc)


def test_alias_matching_is_word_boundary_aware():
    """`admission control` must not register as a cache-miss requirement."""
    hits = {m.id for m in detect_metrics("RG uses admission control at the source")}
    assert "miss_reduction" not in hits


def test_infer_domain_from_clause_text():
    assert infer_domain("report p99 completion latency and goodput vs baseline") == "noc"
    assert infer_domain("predicted MPKI reduction with DRAM bandwidth held flat") == "cache"
    assert infer_domain("PE utilization and data reuse under iso-resource SRAM") == "dataflow"
    assert infer_domain("report hop latency and die-to-die bandwidth") == "wafer"
    assert infer_domain("no metrics named here at all") == "generic"


# --- provenance --------------------------------------------------------------


def test_cache_demo_thresholds_all_come_from_the_spec():
    th = parse_acceptance_thresholds(_load("demo"))
    assert th.domain == "cache"
    assert th.defaulted == frozenset(), "demo.md pins all four gates explicitly"
    assert th.min_miss_reduction == pytest.approx(0.15)
    assert th.max_bw_delta_frac == pytest.approx(0.05)
    assert th.max_magic_gap == pytest.approx(2.0)
    assert th.area_budget_mm2 == pytest.approx(0.5)
    assert th.gradable
    assert th.unmeasurable_metrics == ()


@pytest.mark.parametrize("name", ["noc_request_grant", "noc_low_tail_collectives"])
def test_noc_specs_are_not_silently_graded_as_cache(name):
    th = parse_acceptance_thresholds(_load(name))
    assert th.domain == "noc"
    # The three substantive cache gates are defaults, and say so.
    assert PERFORMANCE_GATES <= th.defaulted
    for gate_field in PERFORMANCE_GATES:
        assert not th.from_spec(gate_field), gate_field
    assert not th.has_spec_performance_gate
    # Measurable now — but report-only, never via invented MPKI gates.
    assert th.gradable
    assert th.report_only
    assert th.spec_gates() == []
    assert "p99_latency" in th.measurable_performance or "completion_latency" in th.measurable_performance


def test_noc_specs_declare_latency_metrics_that_are_now_measurable():
    th = parse_acceptance_thresholds(_load("noc_low_tail_collectives"))
    assert "p99_latency" in th.measurable_performance
    assert "goodput" in th.measurable_performance
    assert "jitter_tolerance" not in th.unmeasurable_metrics
    assert (
        "jitter_tolerance" in th.measurable_declared
        or "jitter_tolerance" in th.measurable_performance
    )
    assert "coverage" not in th.unmeasurable_metrics
    assert (
        "coverage" in th.measurable_declared
        or "coverage" in th.measurable_performance
    )
    assert "magic_gap" in th.declared_metrics
    assert "magic_gap" not in th.unmeasurable_metrics
    assert th.from_spec("max_magic_gap")


def test_magic_gap_alone_does_not_make_a_spec_gradable():
    """Magic Gap is a model-vs-sim consistency check, not a performance target."""
    th = parse_acceptance_thresholds(_load("noc_request_grant"))
    assert th.from_spec("max_magic_gap")
    # Request-grant also declares completion_latency / goodput, which we can measure.
    assert "completion_latency" in th.measurable_performance
    assert th.gradable
    assert th.report_only


def test_provenance_rows_label_every_gate():
    th = parse_acceptance_thresholds(_load("noc_low_tail_collectives"))
    rows = {r[0]: r[2] for r in th.provenance_rows()}
    assert set(rows) == set(GATE_FIELDS)
    assert rows["max_magic_gap"] == "规范声明"
    assert rows["min_miss_reduction"] != "规范声明"


def test_as_dict_carries_provenance_for_reports_and_ui():
    th = parse_acceptance_thresholds(_load("noc_low_tail_collectives"))
    d = th.as_dict()
    assert d["domain"] == "noc"
    assert "min_miss_reduction" in d["defaulted"]
    assert "jitter_tolerance" not in d["unmeasurable_metrics"]
    assert d["report_only"] is True
    assert "p99_latency" in d["measurable_performance"]
    # Legacy consumers still find the four numbers.
    for gate_field in GATE_FIELDS:
        assert gate_field in d


# --- lint --------------------------------------------------------------------


def test_lint_acceptance_flags_remaining_gaps_and_report_only():
    issues = lint_acceptance(_load("noc_low_tail_collectives"))
    joined = "\n".join(issues)
    gap_issues = [i for i in issues if "没有评估器" in i]
    assert not any("jitter_tolerance" in i for i in gap_issues)
    assert not any("coverage" in i for i in gap_issues)
    assert "report-only" in joined
    assert "strict_acc" not in joined


def test_lint_acceptance_is_quiet_for_the_cache_demo():
    assert lint_acceptance(_load("demo")) == []


def test_lint_wafer_explains_yield_thermal_are_not_fabric_metrics(tmp_path):
    path = scaffold_unmeasurable_probe(
        title="wafer clamp probe",
        out_dir=tmp_path,
    )
    issues = lint_acceptance(load_problem_package(path))
    joined = "\n".join(issues)
    assert "yield_redundancy" in joined or "良率" in joined
    assert "热" in joined or "thermal" in joined
    assert "hop" in joined.lower() or "die-to-die" in joined or "织物" in joined


def test_structural_lint_still_passes_for_noc_specs():
    """Ungradable is not the same as malformed; registration must stay allowed."""
    for name in ("noc_request_grant", "noc_low_tail_collectives"):
        assert lint_package(_load(name)) == []


# --- scaffolding -------------------------------------------------------------


@pytest.mark.parametrize("domain", sorted(TEMPLATES))
def test_every_domain_template_scaffolds_and_lints_clean(domain, tmp_path: Path):
    path = scaffold_problem(
        title=f"{domain} probe",
        workload="w",
        symptom="s",
        constraint="c",
        domain=domain,
        out_dir=tmp_path,
    )
    pp = load_problem_package(path)
    assert lint_package(pp) == []
    assert pp.meta["domain"] == domain


def test_scaffolded_domain_is_inferred_back_from_the_clauses():
    """A NoC template must not read as a cache problem after round-tripping."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = scaffold_problem(
            title="noc probe",
            workload="w",
            symptom="s",
            constraint="c",
            domain="noc",
            out_dir=Path(tmp),
        )
        th = parse_acceptance_thresholds(load_problem_package(path))
    assert th.domain == "noc"
    assert th.gradable
    assert th.report_only, "measurable tail latency is not the same as a numeric gate"


def test_scaffolded_dataflow_is_measurable_report_only(tmp_path: Path):
    path = scaffold_problem(
        title="dataflow probe",
        workload="w",
        symptom="s",
        constraint="c",
        domain="dataflow",
        out_dir=tmp_path,
    )
    th = parse_acceptance_thresholds(load_problem_package(path))
    assert th.domain == "dataflow"
    assert th.gradable
    assert th.report_only
    assert "pe_utilization" in th.measurable_performance
    assert not th.has_spec_performance_gate


def test_scaffolded_wafer_is_measurable_report_only(tmp_path: Path):
    path = scaffold_problem(
        title="wafer probe",
        workload="w",
        symptom="s",
        constraint="c",
        domain="wafer",
        out_dir=tmp_path,
    )
    th = parse_acceptance_thresholds(load_problem_package(path))
    assert th.domain == "wafer"
    assert th.gradable
    assert th.report_only
    assert "die_to_die_bw" in th.measurable_performance
    assert "fabric_hop_latency" in th.measurable_performance
    assert not th.has_spec_performance_gate
    assert "yield_redundancy" in th.unmeasurable_metrics
    assert "thermal_density" in th.unmeasurable_metrics


@pytest.mark.parametrize("alias", ["cpu", "memory", "core"])
def test_cpu_memory_aliases_scaffold_as_cache(alias, tmp_path: Path):
    from archzero.spec.wizard import resolve_scaffold_domain

    assert resolve_scaffold_domain(alias) == "cache"
    path = scaffold_problem(
        title=f"{alias} probe",
        workload="SPEC CPU / LLC",
        symptom="MPKI",
        constraint="area",
        domain=alias,
        out_dir=tmp_path,
    )
    pp = load_problem_package(path)
    assert pp.meta["domain"] == "cache"
    th = parse_acceptance_thresholds(pp)
    assert th.domain == "cache"
    assert th.gradable


def test_unknown_domain_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="unknown domain"):
        scaffold_problem(
            title="t",
            workload="w",
            symptom="s",
            constraint="c",
            domain="quantum",
            out_dir=tmp_path,
        )


# --- funnel behaviour --------------------------------------------------------


def test_campaign_does_not_clamp_a_measurable_noc_spec(tmp_cfg):
    from archzero.funnel.pipeline import acc_gate_for_campaign
    from archzero.models import Tier

    tmp_cfg.funnel.strict_acc = True
    through, meta = acc_gate_for_campaign(
        tmp_cfg, _load("noc_low_tail_collectives"), Tier.T4
    )
    assert through is Tier.T4
    assert meta["gradable"] is True
    assert meta["report_only"] is True
    assert meta["backend"] == "noc"
    assert "clamped_from" not in meta


def test_campaign_clamps_to_tier1_for_an_ungradable_spec(tmp_cfg, tmp_path: Path):
    from archzero.funnel.pipeline import acc_gate_for_campaign
    from archzero.models import Tier
    from archzero.spec.ndf import load_problem_package

    tmp_cfg.funnel.strict_acc = True
    path = scaffold_unmeasurable_probe(
        title="wafer clamp probe",
        out_dir=tmp_path,
    )
    through, meta = acc_gate_for_campaign(tmp_cfg, load_problem_package(path), Tier.T4)
    assert through is Tier.T1, "do not bill hundreds of calls toward an MPKI verdict"
    assert meta["clamped_from"] == "tier4"
    assert meta["gradable"] is False


def test_campaign_does_not_clamp_a_gradable_spec(tmp_cfg):
    from archzero.funnel.pipeline import acc_gate_for_campaign
    from archzero.models import Tier

    through, meta = acc_gate_for_campaign(tmp_cfg, _load("demo"), Tier.T4)
    assert through is Tier.T4
    assert meta["gradable"] is True
    assert "clamped_from" not in meta


def test_campaign_clamp_respects_strict_acc_opt_out(tmp_cfg):
    from archzero.funnel.pipeline import acc_gate_for_campaign
    from archzero.models import Tier

    tmp_cfg.funnel.strict_acc = False
    through, meta = acc_gate_for_campaign(
        tmp_cfg, _load("noc_low_tail_collectives"), Tier.T4
    )
    assert through is Tier.T4
    assert meta["gradable"] is True
    assert meta["report_only"] is True


def test_offline_seed_demonstrates_the_refusal_without_an_api_key(tmp_path: Path):
    """A new user must be able to see the honesty property with zero setup."""
    from archzero.config import FactoryConfig
    from archzero.demo_seed import seed_acc_refusal_campaign
    from archzero.models import Tier, Verdict
    from archzero.store.db import Store

    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    result = seed_acc_refusal_campaign(cfg)
    assert result["created"]
    assert result["through"] == "tier1"

    store = Store(cfg.db_path)
    camp = store.get_campaign(result["campaign_id"])
    assert camp is not None
    assert camp.meta["acc"]["clamped_from"] == "tier4"
    assert camp.meta["acc"]["domain"] == "wafer"

    cands = store.list_candidates(campaign_id=camp.id)
    assert cands
    for c in cands:
        verdicts = {t.tier: t.verdict for t in c.tier_history}
        assert verdicts[Tier.T0] is Verdict.PASS
        assert verdicts[Tier.T1] is Verdict.PASS
        assert verdicts[Tier.T2] is Verdict.UNAVAILABLE
        assert not c.hard_passed(Tier.T2)


def test_offline_noc_seed_reports_numbers_without_inventing_a_gate(tmp_path: Path):
    from archzero.config import FactoryConfig
    from archzero.demo_seed import NOC_MECHANISMS, seed_noc_report_campaign
    from archzero.models import Tier, Verdict
    from archzero.store.db import Store

    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    result = seed_noc_report_campaign(cfg)
    assert result["created"]
    assert result["through"] == "tier4"

    store = Store(cfg.db_path)
    camp = store.get_campaign(result["campaign_id"])
    assert camp is not None
    assert camp.meta["acc"]["report_only"] is True
    assert "clamped_from" not in camp.meta["acc"]

    cands = store.list_candidates(campaign_id=camp.id)
    assert len(cands) == len(NOC_MECHANISMS)
    for c in cands:
        assert c.metrics.get("t3_p99_latency")
        assert "t3_miss_reduction" not in c.metrics
        verdicts = {t.tier: t.verdict for t in c.tier_history}
        assert verdicts[Tier.T3] is Verdict.PASS
        assert "report-only" in c.tier_history[-1].summary


def test_offline_dataflow_seed(tmp_path: Path):
    from archzero.config import FactoryConfig
    from archzero.demo_seed import DATAFLOW_MECHANISMS, seed_dataflow_report_campaign
    from archzero.models import Tier, Verdict
    from archzero.store.db import Store

    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    result = seed_dataflow_report_campaign(cfg)
    assert result["created"]
    assert result["through"] == "tier4"

    store = Store(cfg.db_path)
    camp = store.get_campaign(result["campaign_id"])
    assert camp is not None
    assert camp.meta["acc"]["report_only"] is True
    assert "clamped_from" not in camp.meta["acc"]

    cands = store.list_candidates(campaign_id=camp.id)
    assert len(cands) == len(DATAFLOW_MECHANISMS)
    for c in cands:
        assert c.metrics.get("t3_pe_utilization")
        assert "t3_miss_reduction" not in c.metrics
        verdicts = {t.tier: t.verdict for t in c.tier_history}
        assert verdicts[Tier.T3] is Verdict.PASS
        assert "report-only" in c.tier_history[-1].summary


def test_offline_seed_is_idempotent(tmp_path: Path):
    from archzero.config import FactoryConfig
    from archzero.demo_seed import seed_acc_refusal_campaign

    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    first = seed_acc_refusal_campaign(cfg)
    second = seed_acc_refusal_campaign(cfg)
    assert not second["created"]
    assert second["campaign_id"] == first["campaign_id"]


@pytest.mark.asyncio
async def test_tier2_declines_ungradable_spec_instead_of_inventing_a_verdict(
    tmp_cfg, fake_llm
):
    from archzero.funnel.tier2 import evaluate_tier2
    from archzero.models import Candidate, Tier, Verdict
    tmp_cfg.funnel.strict_acc = True
    path = scaffold_unmeasurable_probe(
        title="wafer t2 refuse",
        out_dir=Path(tmp_cfg.state_dir),
    )
    problem = load_problem_package(path)
    cand = Candidate(
        problem_id=problem.id,
        title="Spare-die bypass",
        family="wse_fabric",
        mechanism="Route around defective dies.",
    )

    out = await evaluate_tier2(tmp_cfg, cand, problem, fake_llm)

    last = out.tier_history[-1]
    assert last.tier is Tier.T2
    assert last.verdict is Verdict.UNAVAILABLE
    assert "拒判" in last.summary
    assert out.status == "active"
    assert not out.hard_passed(Tier.T2)
    assert last.metrics["acc_gradable"] is False


@pytest.mark.asyncio
async def test_strict_acc_can_be_disabled_to_accept_cache_defaults(tmp_cfg, fake_llm):
    from archzero.funnel.tier2 import evaluate_tier2
    from archzero.models import Candidate, Tier, Verdict

    tmp_cfg.funnel.strict_acc = False
    problem = _load("noc_low_tail_collectives")
    cand = Candidate(
        problem_id=problem.id,
        title="RG arbiter",
        family="noc_rg",
        mechanism="Grant slots.",
    )

    out = await evaluate_tier2(tmp_cfg, cand, problem, fake_llm)

    last = out.tier_history[-1]
    assert last.tier is Tier.T2
    assert last.verdict is not Verdict.UNAVAILABLE, "opt-out must still grade"
