import { createFileRoute, notFound } from '@tanstack/react-router'
import {
  Box,
  Breadcrumbs,
  Divider,
  Grid,
  Link,
  Stack,
  Typography,
} from '@mui/material'
import LayersOutlinedIcon from '@mui/icons-material/LayersOutlined'
import type { AcquisitionOut, WarningOut } from '~/types'
import { CustomLink } from '~/components/CustomLink'
import { ThumbnailPlaceholder } from '~/components/common/Thumbnail'
import { FileglancerPathSection } from '~/components/common/FileglancerPathSection'
import { TomogramsAnnotationsTable } from '~/components/acquisitions/TomogramsAnnotationsTable'
import {
  sampleDetailQueryOptions,
  sampleWarningsQueryOptions,
  useSampleDetailQuery,
  useSampleWarningsQuery,
} from '~/utils/queryOptions'

export const Route = createFileRoute('/acquisitions/$acquisitionId')({
  validateSearch: (search: Record<string, unknown>) => ({
    sampleId: typeof search.sampleId === 'string' ? search.sampleId : '',
  }),
  loaderDeps: ({ search }) => ({ sampleId: search.sampleId }),
  loader: async ({
    context: { queryClient },
    params: { acquisitionId },
    deps: { sampleId },
  }) => {
    if (!sampleId) throw notFound()
    const [sample] = await Promise.all([
      queryClient.ensureQueryData(sampleDetailQueryOptions(sampleId)),
      queryClient.ensureQueryData(sampleWarningsQueryOptions(sampleId)),
    ])
    if (!sample.acquisitions.some((a) => a.acquisition_id === acquisitionId)) {
      throw notFound()
    }
  },
  component: AcquisitionDetailRoute,
})

// Warnings are recorded per-sample with a dotted `location` like
// `acquisitions.{id}` or `acquisitions.{id}.tomogram[...]` (see
// cryoet_catalog/assembler.py). Match the acquisition's own location and any
// nested child location, but not a sibling whose id shares a prefix.
function warningsForAcquisition(
  warnings: WarningOut[],
  acquisitionId: string,
): WarningOut[] {
  const prefix = `acquisitions.${acquisitionId}`
  return warnings.filter(
    (w) => w.location === prefix || w.location.startsWith(`${prefix}.`),
  )
}

function AcquisitionDetailRoute() {
  const { acquisitionId } = Route.useParams()
  const { sampleId } = Route.useSearch()
  const { data: sample } = useSampleDetailQuery(sampleId)
  const { data: warnings } = useSampleWarningsQuery(sampleId)

  // Guaranteed present — the loader throws notFound otherwise.
  const acquisition = sample.acquisitions.find(
    (a) => a.acquisition_id === acquisitionId,
  ) as AcquisitionOut

  const acqWarnings = warningsForAcquisition(warnings, acquisitionId)

  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit">
          Home
        </CustomLink>
        <CustomLink to="/" color="inherit">
          Browse
        </CustomLink>
        <CustomLink
          to="/samples/$sampleId"
          params={{ sampleId }}
          color="inherit"
        >
          {sampleId}
        </CustomLink>
        <Typography color="text.primary">{acquisitionId}</Typography>
      </Breadcrumbs>

      {/* ── Title section ──────────────────────────────────────────── */}
      <Box>
        <Typography variant="h5" component="h1" gutterBottom>
          {acquisitionId}
        </Typography>

        {acqWarnings.length > 0 ? (
          // /manage isn't built yet; plain link for now (filters to this
          // acquisition's warnings once that route exists).
          <Link
            href={`/manage?sample=${encodeURIComponent(
              sampleId,
            )}&acquisition=${encodeURIComponent(acquisitionId)}`}
            variant="body2"
            fontWeight={700}
          >
            *There are warnings for this acquisition's metadata. Click to view
          </Link>
        ) : null}
      </Box>

      <Divider />

      {/* ── Tilt series + path ─────────────────────────────────────── */}
      <Grid container spacing={4}>
        <Grid item xs={12} md={4}>
          <ThumbnailPlaceholder
            width="100%"
            height={220}
            icon={<LayersOutlinedIcon />}
            label="Tilt series"
          />
        </Grid>

        <Grid item xs={12} md={8}>
          <FileglancerPathSection
            path={acquisition.path}
            metadataFilename="acquisition.toml"
          />
        </Grid>
      </Grid>

      <Divider />

      {/* ── Tomograms and annotations ──────────────────────────────── */}
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
            Tomograms and annotations
          </Typography>
        </Box>
        <TomogramsAnnotationsTable
          sampleId={sampleId}
          acquisition={acquisition}
        />
      </Box>
    </Stack>
  )
}
