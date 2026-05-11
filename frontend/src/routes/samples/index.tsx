import { createFileRoute } from '@tanstack/react-router'
import { EmptyState } from '~/components/common/EmptyState'

export const Route = createFileRoute('/samples/')({
  component: SamplesIndex,
})

function SamplesIndex() {
  return (
    <EmptyState
      title="No sample selected"
      description="Select a row to see details."
    />
  )
}
