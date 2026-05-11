import { useState } from 'react'
import { Box } from '@mui/material'
import { Outlet, createFileRoute, useParams } from '@tanstack/react-router'
import { AppShell } from '~/components/layout/AppShell'
import { Splitter } from '~/components/layout/Splitter'
import { FilterDrawer } from '~/components/filters/FilterDrawer'
import { SamplesTable } from '~/components/samples/SamplesTable'
import {
  filtersOptionsQueryOptions,
  samplesQueryOptions,
  useFiltersOptionsQuery,
  useSamplesQuery,
} from '~/utils/queryOptions'
import {
  buildSamplesQueryString,
  samplesSearchSchema,
  type SamplesSearchParams,
} from '~/utils/samplesSearch'

export const Route = createFileRoute('/samples')({
  validateSearch: samplesSearchSchema,
  loaderDeps: ({ search }) => ({ search }),
  loader: ({ context: { queryClient }, deps: { search } }) =>
    Promise.all([
      queryClient.ensureQueryData(samplesQueryOptions(search)),
      queryClient.ensureQueryData(filtersOptionsQueryOptions),
    ]),
  component: SamplesLayout,
})

function SamplesLayout() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const { data: filterOptions } = useFiltersOptionsQuery()
  // URL search params are the single source of truth for filter state
  // (revised from plan §11.19): every drawer field round-trips through the
  // URL so back/forward, copy/paste, and bookmarks behave uniformly across
  // all filters. The 300 ms debounce inside FilterDrawer still throttles
  // slider drags so we don't navigate on every mouse pixel.
  const { data: samples, isFetching } = useSamplesQuery(search)

  const selectedParams = useParams({
    from: '/samples/$sampleId',
    shouldThrow: false,
  })
  const selectedId = selectedParams?.sampleId

  const [drawerOpen, setDrawerOpen] = useState(true)

  const handleFiltersChange = (next: Partial<SamplesSearchParams>) => {
    navigate({ search: () => next })
  }

  const handleCopyUrl = async (params: Partial<SamplesSearchParams>) => {
    if (typeof window === 'undefined' || !navigator.clipboard) return
    const qs = buildSamplesQueryString(params)
    // Always anchor the shared URL on `/samples` — never include the currently
    // selected sample id, which is unrelated to filter state and may not match
    // the resulting filter set.
    const url = `${window.location.origin}/samples${qs}`
    try {
      await navigator.clipboard.writeText(url)
    } catch {
      // ignore — user can retry
    }
  }

  const handleSelect = (id: string) => {
    navigate({
      to: '/samples/$sampleId',
      params: { sampleId: id },
      search: (prev) => prev,
    })
  }

  return (
    // Break out of the root <Container>: anchor to viewport below the 64 px
    // AppBar. The persistent Drawer paper is also offset by 64 px (see
    // AppShell) so the navbar stays visible above this overlay.
    <Box sx={{ position: 'fixed', top: 64, left: 0, right: 0, bottom: 0 }}>
      <AppShell
        drawer={
          <FilterDrawer
            options={filterOptions}
            initial={search}
            onChange={handleFiltersChange}
            onCopyUrl={handleCopyUrl}
          />
        }
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      >
        <Splitter
          left={
            <SamplesTable
              rows={samples ?? []}
              selectedId={selectedId}
              onSelect={handleSelect}
              loading={isFetching}
            />
          }
          right={<Outlet />}
        />
      </AppShell>
    </Box>
  )
}
