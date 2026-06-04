import {
  keepPreviousData,
  queryOptions,
  useQuery,
  useSuspenseQuery,
} from '@tanstack/react-query'
import { apiFetch } from '~/utils/api'
import {
  buildSamplesQueryString,
  type SamplesSearchParams,
} from '~/utils/samplesSearch'
import type {
  FiltersOptionsOut,
  SampleDetail,
  SampleSummary,
  SampleWarningsGroup,
  ScanOut,
  ScanSampleOut,
  StatsOverviewOut,
  WarningOut,
} from '~/types'

// Endpoints scoped to "the latest completed scan" return 404 when no scan has
// completed yet. Callers want an empty list in that case rather than an error.
async function fetchOrEmpty<T>(path: string): Promise<T[]> {
  try {
    return await apiFetch<T[]>(path)
  } catch (err) {
    if (err instanceof Error && err.message.includes('404')) return []
    throw err
  }
}

type ScanOutcome = 'upserted' | 'skipped' | 'failed'

// ── /samples list ────────────────────────────────────────────────────────────

export const samplesQueryOptions = (params: SamplesSearchParams = {}) =>
  queryOptions({
    queryKey: ['samples', 'list', params],
    queryFn: () =>
      apiFetch<SampleSummary[]>(`/samples${buildSamplesQueryString(params)}`),
  })

// `useQuery` (not `useSuspenseQuery`) + `placeholderData: keepPreviousData`
// so filter edits don't suspend and unmount the table while the new fetch
// is in flight. The route loader still primes the cache via `ensureQueryData`,
// so the first render after navigation has data immediately.
export function useSamplesQuery(params: SamplesSearchParams = {}) {
  return useQuery({
    ...samplesQueryOptions(params),
    placeholderData: keepPreviousData,
  })
}

// ── /samples/{id} detail ─────────────────────────────────────────────────────

export const sampleDetailQueryOptions = (sampleId: string) =>
  queryOptions({
    queryKey: ['samples', 'detail', sampleId],
    queryFn: () =>
      apiFetch<SampleDetail>(`/samples/${encodeURIComponent(sampleId)}`),
  })

export function useSampleDetailQuery(sampleId: string) {
  return useSuspenseQuery(sampleDetailQueryOptions(sampleId))
}

// ── /samples/{id}/warnings ───────────────────────────────────────────────────

export const sampleWarningsQueryOptions = (sampleId: string) =>
  queryOptions({
    queryKey: ['samples', 'warnings', sampleId],
    queryFn: () =>
      apiFetch<WarningOut[]>(
        `/samples/${encodeURIComponent(sampleId)}/warnings`,
      ),
  })

export function useSampleWarningsQuery(sampleId: string) {
  return useSuspenseQuery(sampleWarningsQueryOptions(sampleId))
}

// ── /filters/options ─────────────────────────────────────────────────────────

export const filtersOptionsQueryOptions = queryOptions({
  queryKey: ['filters', 'options'],
  queryFn: () => apiFetch<FiltersOptionsOut>('/filters/options'),
})

export function useFiltersOptionsQuery() {
  return useSuspenseQuery(filtersOptionsQueryOptions)
}

// ── /stats/overview ──────────────────────────────────────────────────────────

export const statsOverviewQueryOptions = queryOptions({
  queryKey: ['stats', 'overview'],
  queryFn: () => apiFetch<StatsOverviewOut>('/stats/overview'),
})

export function useStatsOverviewQuery() {
  return useSuspenseQuery(statsOverviewQueryOptions)
}

// ── /scans list ──────────────────────────────────────────────────────────────

export const scansQueryOptions = queryOptions({
  queryKey: ['scans', 'list'],
  queryFn: () => apiFetch<Array<ScanOut>>('/scans'),
})

export function useScansQuery() {
  return useSuspenseQuery(scansQueryOptions)
}

// ── /scans/{id} (+ /warnings, /samples) ──────────────────────────────────────

// A specific scan run by id. Rejects with a 404 Error when the scan is
// unknown, which the route loader turns into a `notFound()`.
export const scanQueryOptions = (scanId: string) =>
  queryOptions({
    queryKey: ['scans', 'detail', scanId],
    queryFn: () => apiFetch<ScanOut>(`/scans/${encodeURIComponent(scanId)}`),
  })

export function useScanQuery(scanId: string) {
  return useSuspenseQuery(scanQueryOptions(scanId))
}

export const scanWarningsQueryOptions = (scanId: string) =>
  queryOptions({
    queryKey: ['scans', 'detail', scanId, 'warnings'],
    queryFn: () =>
      apiFetch<SampleWarningsGroup[]>(
        `/scans/${encodeURIComponent(scanId)}/warnings`,
      ),
  })

export function useScanWarningsQuery(scanId: string) {
  return useSuspenseQuery(scanWarningsQueryOptions(scanId))
}

export const scanSamplesQueryOptions = (scanId: string, outcome: ScanOutcome) =>
  queryOptions({
    queryKey: ['scans', 'detail', scanId, 'samples', outcome],
    queryFn: () =>
      apiFetch<ScanSampleOut[]>(
        `/scans/${encodeURIComponent(scanId)}/samples?outcome=${outcome}`,
      ),
  })

export function useScanSamplesQuery(scanId: string, outcome: ScanOutcome) {
  return useSuspenseQuery(scanSamplesQueryOptions(scanId, outcome))
}

// ── /scans/latest ────────────────────────────────────────────────────────────

export const latestScanQueryOptions = queryOptions({
  queryKey: ['scans', 'latest'],
  queryFn: async (): Promise<ScanOut | null> => {
    try {
      return await apiFetch<ScanOut>('/scans/latest')
    } catch (err) {
      // 404 means "no completed scan yet" — surface as null so callers can
      // render an empty branch without try/catch.
      if (err instanceof Error && err.message.includes('404')) return null
      throw err
    }
  },
})

export function useLatestScanQuery() {
  return useSuspenseQuery(latestScanQueryOptions)
}

// ── /scans/latest/warnings (grouped by sample) ───────────────────────────────

export const latestScanWarningsQueryOptions = queryOptions({
  queryKey: ['scans', 'latest', 'warnings'],
  queryFn: () => fetchOrEmpty<SampleWarningsGroup>('/scans/latest/warnings'),
})

export function useLatestScanWarningsQuery() {
  return useSuspenseQuery(latestScanWarningsQueryOptions)
}

// ── /scans/latest/samples?outcome= ───────────────────────────────────────────

export const latestScanSamplesQueryOptions = (outcome: ScanOutcome) =>
  queryOptions({
    queryKey: ['scans', 'latest', 'samples', outcome],
    queryFn: () =>
      fetchOrEmpty<ScanSampleOut>(`/scans/latest/samples?outcome=${outcome}`),
  })

export function useLatestScanSamplesQuery(outcome: ScanOutcome) {
  return useSuspenseQuery(latestScanSamplesQueryOptions(outcome))
}
