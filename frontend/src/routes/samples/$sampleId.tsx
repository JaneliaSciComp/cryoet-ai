import { createFileRoute } from '@tanstack/react-router'
import { SampleDetailPanel } from '~/components/samples/SampleDetailPanel'
import {
  sampleDetailQueryOptions,
  sampleWarningsQueryOptions,
} from '~/utils/queryOptions'

export const Route = createFileRoute('/samples/$sampleId')({
  loader: ({ context: { queryClient }, params: { sampleId } }) =>
    Promise.all([
      queryClient.ensureQueryData(sampleDetailQueryOptions(sampleId)),
      queryClient.ensureQueryData(sampleWarningsQueryOptions(sampleId)),
    ]),
  component: SampleDetailRoute,
})

function SampleDetailRoute() {
  const { sampleId } = Route.useParams()
  return <SampleDetailPanel sampleId={sampleId} />
}
