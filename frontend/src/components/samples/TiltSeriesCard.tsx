import { useState } from 'react'
import {
  Box,
  Card,
  CardContent,
  Grid,
  Stack,
  Typography,
} from '@mui/material'
import { EmptyState } from '~/components/common/EmptyState'
import { Lightbox } from '~/components/common/Lightbox'
import { NeuroglancerButton } from '~/components/common/NeuroglancerButton'
import { SubEntityBlock } from './SubEntityBlock'
import type { TiltSeriesOut } from '~/types'

type TiltSeriesCardProps = {
  sampleId: string
  acquisitionId: string
  ts: TiltSeriesOut
}

type PreviewImageProps = {
  src: string
  alt: string
}

function PreviewImage(props: PreviewImageProps) {
  const { src, alt } = props
  const [error, setError] = useState(false)
  const [open, setOpen] = useState(false)

  if (error) {
    return <EmptyState title="Preview unavailable" />
  }
  return (
    <>
      <Box
        component="img"
        loading="lazy"
        src={src}
        alt={alt}
        onError={() => setError(true)}
        onClick={() => setOpen(true)}
        sx={{ width: '100%', cursor: 'pointer', display: 'block' }}
      />
      <Lightbox
        open={open}
        onClose={() => setOpen(false)}
        src={src}
        alt={alt}
      />
    </>
  )
}

export function TiltSeriesCard(props: TiltSeriesCardProps) {
  const { sampleId, acquisitionId, ts } = props

  const base = `/api/tilt-series/${encodeURIComponent(sampleId)}/${encodeURIComponent(acquisitionId)}/${encodeURIComponent(ts.tilt_series_id)}`
  const previewSrc = `${base}/preview.png`
  const polarSrc = `${base}/polar.png`
  const ngPath = `/tilt-series/${encodeURIComponent(sampleId)}/${encodeURIComponent(acquisitionId)}/${encodeURIComponent(ts.tilt_series_id)}/neuroglancer`

  const tiltRange =
    ts.tilt_range_min !== null && ts.tilt_range_max !== null
      ? `${ts.tilt_range_min}..${ts.tilt_range_max}`
      : null

  const entries: Array<[string, unknown]> = [
    ['Number of tilts', ts.n_tilts],
    ['Tilt range', tiltRange],
    ['Voltage', ts.voltage],
    ['Pixel spacing', ts.pixel_spacing],
    ['Image format', ts.image_format],
    ['Microscope', ts.microscope],
    ['Camera', ts.camera],
  ]

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2}>
          <Stack
            direction="row"
            spacing={2}
            alignItems="center"
            justifyContent="space-between"
            flexWrap="wrap"
          >
            <Typography variant="h6">{ts.tilt_series_id}</Typography>
            <NeuroglancerButton launchPath={ngPath} />
          </Stack>

          <SubEntityBlock title="Tilt-series metadata" entries={entries} />

          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <Typography variant="overline">Polar plot</Typography>
              <PreviewImage
                src={polarSrc}
                alt={`Polar plot for ${ts.tilt_series_id}`}
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <Typography variant="overline">Median tilt</Typography>
              <PreviewImage
                src={previewSrc}
                alt={`Median tilt for ${ts.tilt_series_id}`}
              />
            </Grid>
          </Grid>
        </Stack>
      </CardContent>
    </Card>
  )
}
