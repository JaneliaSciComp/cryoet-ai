import { Box, Card, CardContent, Stack, Typography } from '@mui/material'
import { CopyButton } from '~/components/common/CopyButton'
import { SubEntityBlock } from './SubEntityBlock'
import { TiltSeriesCard } from './TiltSeriesCard'
import { TomogramCard } from './TomogramCard'
import { AnnotationList } from './AnnotationList'
import type { AcquisitionOut } from '~/types'

type AcquisitionCardProps = {
  sampleId: string
  acq: AcquisitionOut
}

export function AcquisitionCard(props: AcquisitionCardProps) {
  const { sampleId, acq } = props

  const entries: Array<[string, unknown]> = [
    ['Resolution', acq.resolution],
    ['Microscope', acq.microscope],
    ['Voltage', acq.voltage],
    ['Camera', acq.camera],
    ['Pixel size', acq.pixel_size],
  ]

  return (
    <Card>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h6">{acq.acquisition_id}</Typography>

          <SubEntityBlock title="Acquisition metadata" entries={entries} />

          {acq.path ? (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{ minWidth: 80 }}
              >
                Path:
              </Typography>
              <Typography
                variant="body2"
                sx={{ wordBreak: 'break-all', flex: 1 }}
              >
                {acq.path}
              </Typography>
              <CopyButton text={acq.path} label="Copy path" />
            </Box>
          ) : null}

          {acq.tilt_series.length > 0 ? (
            <Stack spacing={1}>
              <Typography variant="overline">Tilt series</Typography>
              {acq.tilt_series.map((ts) => (
                <TiltSeriesCard
                  key={ts.tilt_series_id}
                  sampleId={sampleId}
                  acquisitionId={acq.acquisition_id}
                  ts={ts}
                />
              ))}
            </Stack>
          ) : null}

          {acq.tomograms.length > 0 ? (
            <Stack spacing={1}>
              <Typography variant="overline">Tomograms</Typography>
              {acq.tomograms.map((t) => (
                <TomogramCard
                  key={t.tomogram_id}
                  sampleId={sampleId}
                  acquisitionId={acq.acquisition_id}
                  tomo={t}
                />
              ))}
            </Stack>
          ) : null}

          <AnnotationList annotations={acq.annotations} />
        </Stack>
      </CardContent>
    </Card>
  )
}
