import { createFileRoute } from '@tanstack/react-router'
import { Typography } from '@mui/material'

type SampleSummary = {
  sample_id: string
  project: string
  data_source: string
  description: string | null
  warning_count: number
}

const API_BASE = import.meta.env.SSR ? 'http://localhost:8000' : '/api'

async function fetchSamples(): Promise<Array<SampleSummary>> {
  const res = await fetch(`${API_BASE}/samples`)
  if (!res.ok) throw new Error(`GET /samples failed: ${res.status}`)
  return res.json()
}

export const Route = createFileRoute('/samples')({
  loader: () => fetchSamples(),
  component: SamplesList,
})

function SamplesList() {
  const data = Route.useLoaderData()

  return (
    <div>
      <Typography variant="h2">Samples</Typography>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Project</th>
            <th>Data source</th>
            <th>Warnings</th>
          </tr>
        </thead>
        <tbody>
          {data.map((s) => (
            <tr key={s.sample_id}>
              <td>{s.sample_id}</td>
              <td>{s.project}</td>
              <td>{s.data_source}</td>
              <td>{s.warning_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
