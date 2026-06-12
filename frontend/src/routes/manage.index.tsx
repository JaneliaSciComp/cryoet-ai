import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Box, Breadcrumbs, Link, Stack, Typography } from "@mui/material";
import { CustomLink } from "~/components/CustomLink";
import { ManageSection } from "~/components/manage/ManageSection";
import { LastScanCard } from "~/components/manage/LastScanCard";
import { SamplesWithWarningsTable } from "~/components/manage/SamplesWithWarningsTable";
import { ScanRunWarningsTable } from "~/components/manage/ScanRunWarningsTable";
import { ScanSamplesTable } from "~/components/manage/ScanSamplesTable";
import {
  latestScanQueryOptions,
  latestScanRunWarningsQueryOptions,
  latestScanSamplesQueryOptions,
  latestScanWarningsQueryOptions,
  useLatestScanQuery,
  useLatestScanRunWarningsQuery,
  useLatestScanSamplesQuery,
  useLatestScanWarningsQuery,
} from "~/utils/queryOptions";

export const Route = createFileRoute("/manage/")({
  loader: ({ context: { queryClient } }) =>
    Promise.all([
      queryClient.ensureQueryData(latestScanQueryOptions),
      queryClient.ensureQueryData(latestScanWarningsQueryOptions),
      queryClient.ensureQueryData(latestScanRunWarningsQueryOptions),
      queryClient.ensureQueryData(latestScanSamplesQueryOptions("upserted")),
      queryClient.ensureQueryData(latestScanSamplesQueryOptions("skipped")),
      queryClient.ensureQueryData(latestScanSamplesQueryOptions("failed")),
    ]),
  component: ManageRoute,
});

// The four expandable sections, keyed so a single "Expand/Collapse all" control
// can drive them together. All default to open.
type SectionKey =
  | "warnings"
  | "runWarnings"
  | "upserted"
  | "skipped"
  | "failed";
const SECTION_KEYS: SectionKey[] = [
  "warnings",
  "runWarnings",
  "upserted",
  "skipped",
  "failed",
];

function ManageRoute() {
  const { data: latestScan } = useLatestScanQuery();
  const { data: warningGroups } = useLatestScanWarningsQuery();
  const { data: runWarnings } = useLatestScanRunWarningsQuery();
  const { data: upserted } = useLatestScanSamplesQuery("upserted");
  const { data: skipped } = useLatestScanSamplesQuery("skipped");
  const { data: failed } = useLatestScanSamplesQuery("failed");

  const [expanded, setExpanded] = useState<Record<SectionKey, boolean>>({
    warnings: true,
    runWarnings: true,
    upserted: true,
    skipped: true,
    failed: true,
  });

  const setSection = (key: SectionKey) => (value: boolean) =>
    setExpanded((prev) => ({ ...prev, [key]: value }));

  const allExpanded = SECTION_KEYS.every((k) => expanded[k]);
  const toggleAll = () => {
    const next = !allExpanded;
    setExpanded({
      warnings: next,
      runWarnings: next,
      upserted: next,
      skipped: next,
      failed: next,
    });
  };

  // Map sample_id -> warning messages, so the "updated or inserted" rows can
  // expand to show their warnings without an extra request.
  const warningsBySample = useMemo(
    () => new Map(warningGroups.map((g) => [g.sample_id, g.warnings])),
    [warningGroups],
  );

  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit" sx={{ fontWeight: 700 }}>
          Home
        </CustomLink>
        <Typography color="text.primary">Manage</Typography>
      </Breadcrumbs>

      <Typography variant="h5" component="h1">
        File system scans
      </Typography>

      <Box>
        <Stack direction="row" spacing={2} alignItems="baseline" sx={{ mb: 1 }}>
          <Typography variant="h6" component="h2">
            Last file system scan
          </Typography>
          {latestScan ? (
            <CustomLink
              to="/manage/$scanId"
              params={{ scanId: latestScan.scan_run_id }}
              variant="body2"
            >
              View scan details
            </CustomLink>
          ) : null}
          <CustomLink to="/manage/all-scans" variant="body2">
            View all scans
          </CustomLink>
        </Stack>
        <LastScanCard scan={latestScan} />
      </Box>

      <Box>
        <Link
          component="button"
          type="button"
          variant="body2"
          onClick={toggleAll}
        >
          {allExpanded ? "Collapse all" : "Expand all"}
        </Link>
      </Box>

      <ManageSection
        count={warningGroups.length}
        title="Samples with warnings"
        expanded={expanded.warnings}
        onChange={setSection("warnings")}
      >
        <SamplesWithWarningsTable groups={warningGroups} />
      </ManageSection>

      <ManageSection
        count={runWarnings.length}
        title="Scan-level issues"
        expanded={expanded.runWarnings}
        onChange={setSection("runWarnings")}
      >
        <ScanRunWarningsTable warnings={runWarnings} />
      </ManageSection>

      <ManageSection
        count={upserted.length}
        title="Samples updated or inserted"
        expanded={expanded.upserted}
        onChange={setSection("upserted")}
      >
        <ScanSamplesTable
          outcome="upserted"
          rows={upserted}
          warningsBySample={warningsBySample}
        />
      </ManageSection>

      <ManageSection
        count={skipped.length}
        title="Samples skipped"
        expanded={expanded.skipped}
        onChange={setSection("skipped")}
      >
        <ScanSamplesTable
          outcome="skipped"
          rows={skipped}
          warningsBySample={warningsBySample}
        />
      </ManageSection>

      <ManageSection
        count={failed.length}
        title="Samples failed"
        expanded={expanded.failed}
        onChange={setSection("failed")}
      >
        <ScanSamplesTable
          outcome="failed"
          rows={failed}
          warningsBySample={warningsBySample}
        />
      </ManageSection>
    </Stack>
  );
}
