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
import {
  samplesSearchSchema,
  type SamplesSearchParams,
} from '~/utils/samplesSearch'
import { StatsBanner } from '~/components/landing/StatsBanner'
import {
  LandingFilters,
  type LandingFilterState,
} from '~/components/landing/LandingFilters'
import { CoverageSummary } from '~/components/landing/CoverageSummary'
import { SamplesPortalTable } from '~/components/landing/SamplesPortalTable'

export const Route = createFileRoute('/')({
  // The URL is the source of truth for filters: validate + coerce search params
  // through the shared schema so a shared/bookmarked link round-trips.
  validateSearch: (search): SamplesSearchParams =>
    samplesSearchSchema.parse(search),
  loaderDeps: ({ search }) => ({ search }),
  loader: ({ context: { queryClient }, deps: { search } }) =>
    Promise.all([
      queryClient.ensureQueryData(statsOverviewQueryOptions),
      queryClient.ensureQueryData(filtersOptionsQueryOptions),
      // Prime the cache with the filtered list so the first render after
      // navigation (or a fresh load of a filtered URL) has data immediately.
      queryClient.ensureQueryData(samplesQueryOptions(search)),
    ]),
  component: Home,
})

// ── URL search <-> drawer state ──────────────────────────────────────────────
// The drawer models a simplified, single-valued shape (`LandingFilterState`);
// the URL holds the full `SamplesSearchParams` (e.g. `microscope` is an array).
// These two helpers translate between them.

function searchToFilters(s: SamplesSearchParams): LandingFilterState {
  return {
    project: s.project,
    data_source: s.data_source,
    microscope: s.microscope?.[0],
    pixel_size_min: s.pixel_size_min,
    pixel_size_max: s.pixel_size_max,
    n_tilts_min: s.n_tilts_min,
    n_tilts_max: s.n_tilts_max,
    has_tomograms: s.has_tomograms,
  }
}

function applyFilterPatch(
  prev: SamplesSearchParams,
  patch: Partial<LandingFilterState>,
): SamplesSearchParams {
  const next: SamplesSearchParams = { ...prev }
  const set = <K extends keyof SamplesSearchParams>(
    key: K,
    value: SamplesSearchParams[K] | undefined,
  ) => {
    // Drop empty values so they don't linger as bare keys in the URL.
    if (value === undefined) delete next[key]
    else next[key] = value
  }

  if ('project' in patch) set('project', patch.project)
  if ('data_source' in patch) set('data_source', patch.data_source)
  if ('microscope' in patch)
    set('microscope', patch.microscope ? [patch.microscope] : undefined)
  if ('pixel_size_min' in patch) set('pixel_size_min', patch.pixel_size_min)
  if ('pixel_size_max' in patch) set('pixel_size_max', patch.pixel_size_max)
  if ('n_tilts_min' in patch) set('n_tilts_min', patch.n_tilts_min)
  if ('n_tilts_max' in patch) set('n_tilts_max', patch.n_tilts_max)
  if ('has_tomograms' in patch)
    set('has_tomograms', patch.has_tomograms ? true : undefined)
  return next
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

  const search = Route.useSearch()
  const navigate = Route.useNavigate()

  // The URL updates immediately on every change (for shareability); debounce
  // only the value that drives the query so typing in the range fields doesn't
  // fire a request per keystroke.
  const debouncedSearch = useDebounce(search, 300)
  const { data: samples, isFetching } = useSamplesQuery(debouncedSearch)
  const rows = samples ?? []

  const filters = searchToFilters(search)

  const patch = (p: Partial<LandingFilterState>) =>
    navigate({ search: (prev) => applyFilterPatch(prev, p), replace: true })
  const clearKey = (key: keyof LandingFilterState) =>
    navigate({
      search: (prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      },
      replace: true,
    })
  const reset = () => navigate({ search: {}, replace: true })

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
