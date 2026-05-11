import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { apiFetch } from '~/utils/api'
import type { SampleSummary } from '~/types'

export const samplesQueryOptions = queryOptions({
  queryKey: ['samples'],
  queryFn: () => apiFetch<Array<SampleSummary>>('/samples'),
})

export function useSamplesQuery() {
  return useSuspenseQuery(samplesQueryOptions)
}
