import { createFileRoute } from '@tanstack/react-router'
import {
  Box,
  Breadcrumbs,
  Divider,
  Grid,
  Link,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import type { SampleDetail } from '~/types'
import { CustomLink } from '~/components/CustomLink'
import { PreviewThumbnail, tomogramThumbnailUrl, acquisitionRepTomogramId } from '~/components/common/Thumbnail'
import { FileglancerPathSection } from '~/components/common/FileglancerPathSection'
import { SampleAcquisitionsTable } from '~/components/samples/SampleAcquisitionsTable'
import {
  sampleDetailQueryOptions,
  sampleWarningsQueryOptions,
  useSampleDetailQuery,
  useSampleWarningsQuery,
} from '~/utils/queryOptions'

export const Route = createFileRoute('/samples/$sampleId')({
  loader: ({ context: { queryClient }, params: { sampleId } }) =>
    Promise.all([
      queryClient.ensureQueryData(sampleDetailQueryOptions(sampleId)),
      queryClient.ensureQueryData(sampleWarningsQueryOptions(sampleId)),
    ]),
  component: SampleDetailRoute,
})

// Fallback for DB rows scanned before `sample.path` existed: derive it from an
// acquisition path, which the scanner stores as `{sample_dir}/{acquisition_id}`
// — so the sample directory is its parent. Prefer `sample.path` when present.
function deriveSamplePath(sample: SampleDetail): string | null {
  const acqPath = sample.acquisitions.find((a) => a.path)?.path
  if (!acqPath) return null
  const trimmed = acqPath.replace(/\/+$/, '')
  const idx = trimmed.lastIndexOf('/')
  return idx > 0 ? trimmed.slice(0, idx) : trimmed
}

function countTomograms(sample: SampleDetail): number {
  return sample.acquisitions.reduce(
    (sum, a) => sum + (a.raw_tomogram ? 1 : 0) + a.post_processed_tomograms.length,
    0,
  )
}

function countAnnotations(sample: SampleDetail): number {
  return sample.acquisitions.reduce((sum, a) => sum + a.annotations.length, 0)
}

function SampleContentsCard(props: { sample: SampleDetail }) {
  const { sample } = props
  const rows: Array<[string, number]> = [
    ['Acquisitions', sample.acquisitions.length],
    ['Tomograms', countTomograms(sample)],
    ['Annotations', countAnnotations(sample)],
  ]
  return (
    <Paper
      variant="outlined"
      sx={{ px: 2.5, py: 2, borderRadius: 2, maxWidth: 320 }}
    >
      <Typography variant="subtitle2" gutterBottom>
        Sample contents
      </Typography>
      <Stack spacing={0.5}>
        {rows.map(([label, value]) => (
          <Box
            key={label}
            sx={{ display: 'flex', justifyContent: 'space-between', gap: 4 }}
          >
            <Typography variant="body2" color="text.secondary">
              {label}
            </Typography>
            <Typography variant="body2">{value.toLocaleString()}</Typography>
          </Box>
        ))}
      </Stack>
    </Paper>
  )
}

function SampleDetailRoute() {
  const { sampleId } = Route.useParams()
  const { data: sample } = useSampleDetailQuery(sampleId)
  const { data: warnings } = useSampleWarningsQuery(sampleId)

  const samplePath = sample.path ?? deriveSamplePath(sample)

  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit">
          Home
        </CustomLink>
        <CustomLink to="/" color="inherit">
          Browse
        </CustomLink>
        <Typography color="text.primary">{sampleId}</Typography>
      </Breadcrumbs>

      {/* ── Title section ──────────────────────────────────────────── */}
      <Box>
        <Typography variant="h5" component="h1" gutterBottom>
          {sampleId}
        </Typography>

        {warnings.length > 0 ? (
          // /manage isn't built yet; plain link for now (filters to this
          // sample's warnings once that route exists).
          <Link
            href={`/manage?sample=${encodeURIComponent(sampleId)}`}
            variant="body2"
            fontWeight={700}
          >
            *There are warnings for this sample's metadata. Click to view
          </Link>
        ) : null}

        {sample.description ? (
          <Typography
            variant="body1"
            color="text.secondary"
            sx={{ mt: warnings.length > 0 ? 1 : 0 }}
          >
            {sample.description}
          </Typography>
        ) : null}
      </Box>

      <Divider />

      {/* ── Details summary ────────────────────────────────────────── */}
      <Grid container spacing={4}>
        <Grid item xs={12} md={4}>
          {(() => {
            const sorted = [...sample.acquisitions].sort((a, b) =>
              a.acquisition_id.localeCompare(b.acquisition_id),
            )
            const firstWithRep = sorted.find(
              (a) => acquisitionRepTomogramId(a) !== null,
            )
            const repId = firstWithRep ? acquisitionRepTomogramId(firstWithRep) : null
            const src = firstWithRep && repId
              ? tomogramThumbnailUrl(sample.sample_id, firstWithRep.acquisition_id, repId)
              : null
            return <PreviewThumbnail src={src} width="100%" height={220} />
          })()}
        </Grid>

        <Grid item xs={12} md={8}>
          <FileglancerPathSection
            path={samplePath}
            metadataFilename="sample.toml"
          >
            <SampleContentsCard sample={sample} />
          </FileglancerPathSection>
        </Grid>
      </Grid>

      <Divider />

      {/* ── Acquisitions ───────────────────────────────────────────── */}
      <Box>
        <Box
          sx={{
            bgcolor: 'action.hover',
            borderRadius: 2,
            px: 2,
            py: 1.25,
            mb: 2,
          }}
        >
          <Typography variant="h6" component="h2">
            Acquisitions ({sample.acquisitions.length.toLocaleString()})
          </Typography>
        </Box>
        <SampleAcquisitionsTable
          sampleId={sampleId}
          acquisitions={sample.acquisitions}
        />
      </Box>
    </Stack>
  )
}
