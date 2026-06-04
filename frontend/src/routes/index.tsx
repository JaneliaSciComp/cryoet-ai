import { useMemo, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import {
  Box,
  Chip,
  Divider,
  Grid,
  Stack,
  Typography,
} from '@mui/material'
import {
  filtersOptionsQueryOptions,
  samplesQueryOptions,
  statsOverviewQueryOptions,
  useFiltersOptionsQuery,
  useSamplesQuery,
  useStatsOverviewQuery,
} from '~/utils/queryOptions'
import { useDebounce } from '~/hooks/useDebounce'
import { StatsBanner } from '~/components/landing/StatsBanner'
import {
  LandingFilters,
  type LandingFilterState,
} from '~/components/landing/LandingFilters'
import { CoverageSummary } from '~/components/landing/CoverageSummary'
import { SamplesPortalTable } from '~/components/landing/SamplesPortalTable'
import type { SamplesSearchParams } from '~/utils/samplesSearch'

export const Route = createFileRoute('/')({
  loader: ({ context: { queryClient } }) =>
    Promise.all([
      queryClient.ensureQueryData(statsOverviewQueryOptions),
      queryClient.ensureQueryData(filtersOptionsQueryOptions),
      queryClient.ensureQueryData(samplesQueryOptions({})),
    ]),
  component: Home,
})

function toQueryParams(f: LandingFilterState): SamplesSearchParams {
  return {
    project: f.project,
    data_source: f.data_source,
    microscope: f.microscope ? [f.microscope] : undefined,
    pixel_size_min: f.pixel_size_min,
    pixel_size_max: f.pixel_size_max,
    n_tilts_min: f.n_tilts_min,
    n_tilts_max: f.n_tilts_max,
    has_tomograms: f.has_tomograms,
  }
}

function activeChips(
  f: LandingFilterState,
): Array<{ key: keyof LandingFilterState; label: string }> {
  const chips: Array<{ key: keyof LandingFilterState; label: string }> = []
  if (f.project) chips.push({ key: 'project', label: `Project: ${f.project}` })
  if (f.data_source)
    chips.push({ key: 'data_source', label: `Data source: ${f.data_source}` })
  if (f.microscope)
    chips.push({ key: 'microscope', label: `Microscope: ${f.microscope}` })
  if (f.pixel_size_min != null)
    chips.push({ key: 'pixel_size_min', label: `Pixel size ≥ ${f.pixel_size_min}` })
  if (f.pixel_size_max != null)
    chips.push({ key: 'pixel_size_max', label: `Pixel size ≤ ${f.pixel_size_max}` })
  if (f.n_tilts_min != null)
    chips.push({ key: 'n_tilts_min', label: `Tilts ≥ ${f.n_tilts_min}` })
  if (f.n_tilts_max != null)
    chips.push({ key: 'n_tilts_max', label: `Tilts ≤ ${f.n_tilts_max}` })
  if (f.has_tomograms)
    chips.push({ key: 'has_tomograms', label: 'Has tomograms' })
  return chips
}

function Home() {
  const { data: stats } = useStatsOverviewQuery()
  const { data: filterOptions } = useFiltersOptionsQuery()

  const [filters, setFilters] = useState<LandingFilterState>({})
  const debouncedFilters = useDebounce(filters, 300)
  const queryParams = useMemo(
    () => toQueryParams(debouncedFilters),
    [debouncedFilters],
  )
  const { data: samples, isFetching } = useSamplesQuery(queryParams)
  const rows = samples ?? []

  const patch = (p: Partial<LandingFilterState>) =>
    setFilters((prev) => ({ ...prev, ...p }))
  const clearKey = (key: keyof LandingFilterState) =>
    setFilters((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
  const reset = () => setFilters({})

  const chips = activeChips(filters)

  return (
    <Stack spacing={4}>
      <StatsBanner stats={stats} />

      <Grid container spacing={4}>
        <Grid item xs={12} md={3}>
          <LandingFilters
            options={filterOptions}
            value={filters}
            onChange={patch}
            onReset={reset}
          />
        </Grid>

        <Grid item xs={12} md={9}>
          <Stack spacing={3}>
            <Box>
              <Typography variant="h6">
                Showing {rows.length.toLocaleString()} of{' '}
                {stats.totals.samples.toLocaleString()} samples
              </Typography>
              {chips.length > 0 ? (
                <Stack
                  direction="row"
                  spacing={1}
                  alignItems="center"
                  flexWrap="wrap"
                  useFlexGap
                  sx={{ mt: 1 }}
                >
                  <Typography variant="body2" color="text.secondary">
                    Filtered by:
                  </Typography>
                  {chips.map((c) => (
                    <Chip
                      key={c.key}
                      size="small"
                      label={c.label}
                      onDelete={() => clearKey(c.key)}
                    />
                  ))}
                  <Chip
                    size="small"
                    color="primary"
                    label="Clear all"
                    onClick={reset}
                  />
                </Stack>
              ) : null}
            </Box>

            <Divider />

            <CoverageSummary rows={rows} />

            <Divider />

            <Box>
              <Typography variant="h6" gutterBottom>
                Samples ({rows.length.toLocaleString()})
              </Typography>
              <SamplesPortalTable rows={rows} loading={isFetching} />
            </Box>
          </Stack>
        </Grid>
      </Grid>
    </Stack>
  )
}
