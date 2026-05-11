import { createFileRoute } from '@tanstack/react-router'
import { Typography } from '@mui/material'
import { z } from 'zod'
import { samplesQueryOptions, useSamplesQuery } from '~/hooks/useSamples'

export const samplesSearchSchema = z.object({
  // URL-canonical fields (§9.1)
  project: z.string().optional(),
  data_source: z.string().optional(),
  q: z.string().optional(),
  sort: z.enum(['sample_id', 'project', 'type']).optional(),
  order: z.enum(['asc', 'desc']).optional(),
  limit: z.coerce.number().int().positive().optional(),
  offset: z.coerce.number().int().nonnegative().optional(),
  // Drawer fields (extended, all optional so shared URLs round-trip)
  type: z.array(z.string()).optional(),
  microscope: z.array(z.string()).optional(),
  voltage: z.array(z.coerce.number()).optional(),
  camera: z.array(z.string()).optional(),
  image_format: z.array(z.string()).optional(),
  has_tomograms: z.coerce.boolean().optional(),
  pixel_size_min: z.coerce.number().optional(),
  pixel_size_max: z.coerce.number().optional(),
  voxel_spacing_min: z.coerce.number().optional(),
  voxel_spacing_max: z.coerce.number().optional(),
  n_tilts_min: z.coerce.number().int().optional(),
  n_tilts_max: z.coerce.number().int().optional(),
})

export type SamplesSearchParams = z.infer<typeof samplesSearchSchema>

export const Route = createFileRoute('/samples')({
  validateSearch: samplesSearchSchema,
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureQueryData(samplesQueryOptions),
  component: SamplesList,
})

function SamplesList() {
  const { data } = useSamplesQuery()

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
