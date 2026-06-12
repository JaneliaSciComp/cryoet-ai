#!/usr/bin/env python3
"""
relion_to_portal.py — map a RELION-5 tomography pipeline into the CZI CryoET
Data Portal sample layout ({sample}/{acq}/{Frames,Gains,TiltSeries,Alignments,
Reconstructions/Tomograms}/), using each job's canonical _rlnJobTypeLabel rather
than the arbitrary jobNNN number.

Routing (matched on job-type family, so e.g. relion.motioncorr.own -> motioncorr):
  relion.importtomo            -> Frames/        (raw movies + mdoc + shared gain)
  relion.motioncorr            -> (skipped; motion-corrected frames, not portal-required)
  relion.ctffind               -> (skipped; CTF metadata only)
  relion.excludetilts          -> (skipped; tilt-selection star only)
  relion.aligntiltseries       -> SPLIT: <acq>.mrc + <acq>.rawtlt -> TiltSeries/
                                          <acq>.aln + <acq>.com    -> Alignments/
  relion.reconstructtomograms  -> Reconstructions/Tomograms/reconstruct_halves/
  relion.denoisetomo           -> Reconstructions/Tomograms/denoised/

Default is a DRY RUN that prints the plan. Pass --apply to act, and choose an
action with --symlink (default), --copy, or --move.

Usage:
  python relion_to_portal.py PIPELINE_DIR TARGET_SAMPLE_DIR
  python relion_to_portal.py PIPELINE_DIR TARGET_SAMPLE_DIR --apply
  python relion_to_portal.py PIPELINE_DIR TARGET_SAMPLE_DIR --apply --copy
"""
from __future__ import annotations
import argparse
import os
import re
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# minimal STAR loop reader (no external deps)
# ---------------------------------------------------------------------------
def read_star_loops(path: Path) -> dict[str, list[dict[str, str]]]:
    """Return {block_name: [ {column: value}, ... ]} for every loop_ table."""
    blocks: dict[str, list[dict]] = {}
    block = None
    cols: list[str] = []
    in_loop = False
    rows: list[dict] = []
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if line.startswith("data_"):
            block = line[len("data_"):] or "_unnamed"
            cols, in_loop, rows = [], False, []
            blocks[block] = rows
            continue
        if line == "loop_":
            in_loop, cols = True, []
            continue
        if in_loop and line.startswith("_"):
            cols.append(line.split()[0][1:])      # strip leading "_", drop "#1"
            continue
        if in_loop and line and not line.startswith(("#", "_")):
            vals = line.split()
            if len(vals) >= len(cols):
                rows.append(dict(zip(cols, vals)))
        elif in_loop and not line:
            in_loop = False
    return blocks


# ---------------------------------------------------------------------------
# job discovery by canonical label
# ---------------------------------------------------------------------------
LABEL_RE = re.compile(r"_rlnJobTypeLabel\s+(\S+)")

# job-type family -> short tag used for discovery
FAMILIES = (
    "relion.importtomo",
    "relion.motioncorr",
    "relion.ctffind",
    "relion.excludetilts",
    "relion.aligntiltseries",
    "relion.reconstructtomograms",
    "relion.denoisetomo",
)

def job_label(jobdir: Path) -> str | None:
    js = jobdir / "job.star"
    if not js.exists():
        return None
    m = LABEL_RE.search(js.read_text(errors="ignore"))
    return m.group(1) if m else None

def job_ok(jobdir: Path) -> bool:
    return (jobdir / "RELION_JOB_EXIT_SUCCESS").exists()

def family_of(label: str | None) -> str | None:
    if not label:
        return None
    for fam in FAMILIES:
        if label == fam or label.startswith(fam + "."):
            return fam
    return None

def discover_jobs(pipeline: Path) -> dict[str, Path]:
    """family -> chosen jobdir (successful; highest jobNNN if several)."""
    found: dict[str, list[Path]] = {}
    for jobdir in sorted(pipeline.glob("job*")):
        fam = family_of(job_label(jobdir))
        if fam:
            found.setdefault(fam, []).append(jobdir)
    chosen: dict[str, Path] = {}
    for fam, dirs in found.items():
        ok = [d for d in dirs if job_ok(d)] or dirs
        # prefer the highest-numbered successful job
        chosen[fam] = sorted(ok, key=lambda d: d.name)[-1]
        if len(dirs) > 1:
            others = ", ".join(d.name for d in dirs if d != chosen[fam])
            print(f"  note: multiple {fam} jobs; using {chosen[fam].name} (ignoring {others})")
        if not any(job_ok(d) for d in dirs):
            print(f"  WARNING: {fam} job {chosen[fam].name} has no RELION_JOB_EXIT_SUCCESS")
    return chosen


# ---------------------------------------------------------------------------
# build the per-acquisition file plan
# ---------------------------------------------------------------------------
def find_gain(pipeline: Path) -> Path | None:
    for ext in ("*.gain", "*.dm4"):
        hits = sorted(pipeline.glob(ext))
        if hits:
            return hits[0]
    # an MRC at the pipeline root is most likely a gain ref
    hits = sorted(pipeline.glob("*.mrc"))
    return hits[0] if hits else None

def find_mdoc(pipeline: Path, acq: str) -> Path | None:
    for cand in (pipeline / "mdocs" / f"{acq}.mdoc", pipeline / f"{acq}.mdoc"):
        if cand.exists():
            return cand
    hits = list(pipeline.glob(f"**/{acq}.mdoc"))
    return hits[0] if hits else None

def build_plan(pipeline: Path, target: Path, jobs: dict[str, Path]) -> dict[str, list[tuple[Path, Path]]]:
    """Return {acq: [(src, dst), ...]}."""
    plan: dict[str, list[tuple[Path, Path]]] = {}

    imp = jobs.get("relion.importtomo")
    if not imp:
        sys.exit("ERROR: no relion.importtomo job found — cannot enumerate acquisitions.")
    catalog = imp / "tilt_series.star"
    glob_block = read_star_loops(catalog).get("global", [])
    # the catalog stores RELION project-relative paths ("Import/jobNNN/..."),
    # which need not exist on disk; resolve the per-acq star from the job dir.
    acqs = [(r["rlnTomoName"], imp / "tilt_series" / f"{r['rlnTomoName']}.star")
            for r in glob_block]
    if not acqs:
        sys.exit(f"ERROR: no acquisitions in {catalog}")

    gain = find_gain(pipeline)
    align = jobs.get("relion.aligntiltseries")
    recon = jobs.get("relion.reconstructtomograms")
    denoise = jobs.get("relion.denoisetomo")

    for acq, acq_star in acqs:
        moves: list[tuple[Path, Path]] = []
        base = target / acq

        # --- Frames: raw movies (from import star) + mdoc + gain ---
        if acq_star.exists():
            rows = read_star_loops(acq_star).get(acq, [])
            for r in rows:
                mv = r.get("rlnMicrographMovieName")
                if mv:
                    src = (pipeline / mv).resolve()
                    moves.append((src, base / "Frames" / src.name))
        mdoc = find_mdoc(pipeline, acq)
        if mdoc:
            moves.append((mdoc, base / "Frames" / mdoc.name))
        if gain:
            moves.append((gain, base / "Gains" / gain.name))

        # --- TiltSeries + Alignments: split the align job's external/<acq>/ ---
        if align:
            ext = align / "external" / acq
            if ext.is_dir():
                # prefer the canonical "<acq>.rawtlt"; ignore variants like
                # "new_<acq>.rawtlt" unless it's the only rawtlt present.
                rawtlts = sorted(ext.glob("*.rawtlt"))
                keep_rawtlt = ext / f"{acq}.rawtlt"
                if not keep_rawtlt.exists():
                    keep_rawtlt = rawtlts[0] if rawtlts else None
                for f in sorted(ext.iterdir()):
                    if not f.is_file():
                        continue
                    n = f.name
                    if n == f"{acq}.mrc":
                        moves.append((f, base / "TiltSeries" / n))
                    elif f == keep_rawtlt:
                        moves.append((f, base / "TiltSeries" / n))
                    elif n.endswith((".aln", ".com")):
                        moves.append((f, base / "Alignments" / n))
                    # everything else (_aligned.mrc, _ctf.mrc, extra *.rawtlt,
                    # *.eps, *.txt, *.log) is derived/CTF -> intentionally skipped

        # --- Reconstructions/Tomograms ---
        if recon:
            for half in (1, 2):
                f = recon / "tomograms" / f"rec_{acq}_half{half}.mrc"
                if f.exists():
                    moves.append((f, base / "Reconstructions" / "Tomograms" / "reconstruct_halves" / f.name))
        if denoise:
            f = denoise / "tomograms" / f"rec_{acq}.mrc"
            if f.exists():
                moves.append((f, base / "Reconstructions" / "Tomograms" / "denoised" / f.name))

        plan[acq] = moves
    return plan


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------
def execute(plan, action: str, apply: bool):
    fold = {"Frames": 0, "Gains": 0, "TiltSeries": 0, "Alignments": 0, "Reconstructions": 0}
    total = 0
    missing = 0
    for acq, moves in plan.items():
        print(f"\n=== {acq} ===")
        per = {}
        for src, dst in moves:
            # category = the path component right after the acquisition dir
            parts = dst.parts
            category = parts[parts.index(acq) + 1]
            per.setdefault(category, []).append((src, dst))
        for category, items in per.items():
            ok = sum(1 for s, _ in items if s.exists())
            miss = len(items) - ok
            print(f"  {category}/  ({ok} files" + (f", {miss} MISSING" if miss else "") + ")")
            # show one example mapping
            s0, d0 = items[0]
            print(f"      e.g. {s0}  ->  {d0}")
            fold[category if category in fold else "Reconstructions"] += ok
            total += ok
            missing += miss
            if apply:
                for src, dst in items:
                    if not src.exists():
                        continue
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if action == "copy":
                        shutil.copy2(src, dst)
                    elif action == "move":
                        shutil.move(str(src), str(dst))
                    elif action == "symlink":
                        if dst.exists() or dst.is_symlink():
                            dst.unlink()
                        os.symlink(src, dst)
    print("\n" + "-" * 60)
    print(f"{'APPLIED' if apply else 'DRY RUN'} — action={action}")
    print(f"  totals: {fold}")
    print(f"  {total} files routed" + (f", {missing} missing sources" if missing else ""))
    if not apply:
        print("  (nothing written — re-run with --apply to act)")


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024 or unit == "T":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{n}B"

# why an unrouted file was left behind, keyed by job-type family
SKIP_REASON = {
    "relion.motioncorr": "motion-corrected frames (regenerable; no portal slot)",
    "relion.ctffind":    "CTF estimation output (no portal slot)",
    "relion.excludetilts": "tilt-selection provenance (.star)",
    "relion.importtomo": "import provenance / unprocessed raw",
    "relion.aligntiltseries": "alignment QC / derived stacks (aligned/ctf)",
    "relion.reconstructtomograms": "reconstruction provenance (.star/logs)",
    "relion.denoisetomo": "denoise provenance / training config",
}

def write_manifest(pipeline: Path, target: Path, plan, jobs, csv_path: Path):
    import csv
    # map: routed source -> (acquisition, portal_category, portal_dest)
    routed = {}
    for acq, moves in plan.items():
        for src, dst in moves:
            parts = dst.parts
            category = parts[parts.index(acq) + 1]
            routed[src.resolve()] = (acq, category, dst)
    # reverse map jobNNN dir name -> family (for classifying unrouted files)
    name_fam = {j.name: fam for fam, j in jobs.items()}

    rows = []
    for p in sorted(pipeline.rglob("*")):
        if not p.is_file():
            continue
        rp = p.resolve()
        rel = rp.relative_to(pipeline)
        top = rel.parts[0] if len(rel.parts) > 1 else "(root)"
        try:
            size = rp.stat().st_size
        except OSError:
            size = 0
        if rp in routed:
            acq, category, dst = routed[rp]
            rows.append({
                "status": "routed", "source": str(rel), "size_bytes": size,
                "size": human_size(size), "acquisition": acq,
                "portal_category": category,
                "portal_dest": str(dst.relative_to(target)), "note": "",
            })
        else:
            fam = name_fam.get(top)
            note = SKIP_REASON.get(fam, "")
            if rel.name == ".DS_Store":
                note = "macOS junk (safe to delete)"
            elif top == "frames":
                note = "raw EER for an unprocessed acquisition"
            rows.append({
                "status": "unrouted", "source": str(rel), "size_bytes": size,
                "size": human_size(size), "acquisition": "",
                "portal_category": "", "portal_dest": "", "note": note,
            })

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["status", "source", "size_bytes", "size", "acquisition",
              "portal_category", "portal_dest", "note"]
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    r = sum(1 for x in rows if x["status"] == "routed")
    u = len(rows) - r
    rb = sum(x["size_bytes"] for x in rows if x["status"] == "routed")
    ub = sum(x["size_bytes"] for x in rows if x["status"] == "unrouted")
    print(f"\nManifest written: {csv_path}")
    print(f"  {len(rows)} files total -> {r} routed ({human_size(rb)}), {u} unrouted ({human_size(ub)})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pipeline_dir", type=Path)
    ap.add_argument("target_sample_dir", type=Path)
    ap.add_argument("--apply", action="store_true", help="actually perform the action (default: dry run)")
    ap.add_argument("--manifest", type=Path, metavar="CSV",
                    help="write a per-file routed-vs-unrouted inventory (with sizes) to CSV")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--symlink", dest="action", action="store_const", const="symlink", help="symlink files (default); instant, no extra disk")
    g.add_argument("--copy", dest="action", action="store_const", const="copy", help="copy files instead of symlinking (duplicates bytes)")
    g.add_argument("--move", dest="action", action="store_const", const="move", help="move files (destructive)")
    ap.set_defaults(action="symlink")
    args = ap.parse_args()

    pipeline = args.pipeline_dir.resolve()
    if not pipeline.is_dir():
        sys.exit(f"ERROR: pipeline dir not found: {pipeline}")

    print(f"Pipeline: {pipeline}")
    print(f"Target:   {args.target_sample_dir.resolve()}")
    print("\nDiscovered jobs (by _rlnJobTypeLabel):")
    jobs = discover_jobs(pipeline)
    for fam in FAMILIES:
        j = jobs.get(fam)
        print(f"  {fam:30} {'-> ' + j.name if j else '(absent)'}")

    target = args.target_sample_dir.resolve()
    plan = build_plan(pipeline, target, jobs)
    execute(plan, args.action, args.apply)
    if args.manifest:
        write_manifest(pipeline, target, plan, jobs, args.manifest.resolve())


if __name__ == "__main__":
    main()
