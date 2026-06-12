import { useMemo, useState } from 'react'
import { createFileRoute, notFound } from '@tanstack/react-router'
import { Box, Breadcrumbs, Link, Stack, Typography } from '@mui/material'
import { CustomLink } from '~/components/CustomLink'
import { LastScanCard } from '~/components/manage/LastScanCard'
import { ManageSection } from '~/components/manage/ManageSection'
import { ScanRunWarningsTable } from '~/components/manage/ScanRunWarningsTable'
import { ScanSamplesTable } from '~/components/manage/ScanSamplesTable'
import {
  scanQueryOptions,
  scanRunWarningsQueryOptions,
  scanSamplesQueryOptions,
  scanWarningsQueryOptions,
  useScanQuery,
  useScanRunWarningsQuery,
  useScanSamplesQuery,
  useScanWarningsQuery,
} from '~/utils/queryOptions'

export const Route = createFileRoute('/manage/$scanId')({
  loader: async ({ context: { queryClient }, params: { scanId } }) => {
    // The scan must exist; an unknown id 404s, which we surface as notFound.
    try {
      await queryClient.ensureQueryData(scanQueryOptions(scanId))
    } catch (err) {
      if (err instanceof Error && err.message.includes('404')) throw notFound()
      throw err
    }
    await Promise.all([
      queryClient.ensureQueryData(scanWarningsQueryOptions(scanId)),
      queryClient.ensureQueryData(scanRunWarningsQueryOptions(scanId)),
      queryClient.ensureQueryData(scanSamplesQueryOptions(scanId, 'upserted')),
      queryClient.ensureQueryData(scanSamplesQueryOptions(scanId, 'skipped')),
      queryClient.ensureQueryData(scanSamplesQueryOptions(scanId, 'failed')),
    ])
  },
  component: ScanDetailRoute,
})

// Scan timestamps are Unix seconds; render in the viewer's locale.
function formatTs(seconds: number | null): string {
  if (seconds == null) return '—'
  return new Date(seconds * 1000).toLocaleString()
}

// The three expandable outcome sections, keyed so a single "Expand/Collapse
// all" control can drive them together. All default to open.
type SectionKey = 'runWarnings' | 'upserted' | 'skipped' | 'failed'
const SECTION_KEYS: SectionKey[] = [
  'runWarnings',
  'upserted',
  'skipped',
  'failed',
]

function ScanDetailRoute() {
  const { scanId } = Route.useParams()
  const { data: scan } = useScanQuery(scanId)
  const { data: warningGroups } = useScanWarningsQuery(scanId)
  const { data: runWarnings } = useScanRunWarningsQuery(scanId)
  const { data: upserted } = useScanSamplesQuery(scanId, 'upserted')
  const { data: skipped } = useScanSamplesQuery(scanId, 'skipped')
  const { data: failed } = useScanSamplesQuery(scanId, 'failed')

  const [expanded, setExpanded] = useState<Record<SectionKey, boolean>>({
    runWarnings: true,
    upserted: true,
    skipped: true,
    failed: true,
  })

  const setSection = (key: SectionKey) => (value: boolean) =>
    setExpanded((prev) => ({ ...prev, [key]: value }))

  const allExpanded = SECTION_KEYS.every((k) => expanded[k])
  const toggleAll = () => {
    const next = !allExpanded
    setExpanded({
      runWarnings: next,
      upserted: next,
      skipped: next,
      failed: next,
    })
  }

  // Map sample_id -> warning messages, so the "updated or inserted" rows can
  // expand to show their warnings without an extra request.
  const warningsBySample = useMemo(
    () => new Map(warningGroups.map((g) => [g.sample_id, g.warnings])),
    [warningGroups],
  )

  const title = `File system scan ${formatTs(scan.started_at)}`

  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit" sx={{ fontWeight: 700 }}>
          Home
        </CustomLink>
        <CustomLink to="/manage" color="inherit" sx={{ fontWeight: 700 }}>
          Manage
        </CustomLink>
        <Typography color="text.primary">{title}</Typography>
      </Breadcrumbs>

      <Typography variant="h5" component="h1">
        {title}
      </Typography>

      <LastScanCard scan={scan} />

      <Box>
        <Link
          component="button"
          type="button"
          variant="body2"
          onClick={toggleAll}
        >
          {allExpanded ? 'Collapse all' : 'Expand all'}
        </Link>
      </Box>

      <ManageSection
        count={runWarnings.length}
        title="Scan-level issues"
        expanded={expanded.runWarnings}
        onChange={setSection('runWarnings')}
      >
        <ScanRunWarningsTable warnings={runWarnings} />
      </ManageSection>

      <ManageSection
        count={upserted.length}
        title="Samples updated or inserted"
        expanded={expanded.upserted}
        onChange={setSection('upserted')}
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
        onChange={setSection('skipped')}
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
        onChange={setSection('failed')}
      >
        <ScanSamplesTable
          outcome="failed"
          rows={failed}
          warningsBySample={warningsBySample}
        />
      </ManageSection>
    </Stack>
  )
}
