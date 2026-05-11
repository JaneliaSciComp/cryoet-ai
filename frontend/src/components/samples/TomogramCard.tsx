import { useState } from 'react'
import {
  Box,
  Card,
  CardContent,
  Skeleton,
  Stack,
  Typography,
} from '@mui/material'
import { CopyButton } from '~/components/common/CopyButton'
import { EmptyState } from '~/components/common/EmptyState'
import { Lightbox } from '~/components/common/Lightbox'
import { NeuroglancerButton } from '~/components/common/NeuroglancerButton'
import { SubEntityBlock } from './SubEntityBlock'
import type { TomogramOut } from '~/types'

type TomogramCardProps = {
  sampleId: string
  acquisitionId: string
  tomo: TomogramOut
}

function formatBytes(bytes: number | null): string | null {
  if (bytes === null || bytes === undefined) return null
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(
    units.length - 1,
    Math.floor(Math.log(bytes) / Math.log(1024)),
  )
  const value = bytes / Math.pow(1024, i)
  return `${value.toFixed(value >= 100 || i === 0 ? 0 : 1)} ${units[i]}`
}

function PathRow(props: { label: string; path: string }) {
  const { label, path } = props
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ minWidth: 80 }}
      >
        {label}:
      </Typography>
      <Typography
        variant="body2"
        sx={{ wordBreak: 'break-all', flex: 1 }}
      >
        {path}
      </Typography>
      <CopyButton text={path} label={`Copy ${label}`} />
    </Box>
  )
}

export function TomogramCard(props: TomogramCardProps) {
  const { sampleId, acquisitionId, tomo } = props
  const [imgLoaded, setImgLoaded] = useState(false)
  const [imgError, setImgError] = useState(false)
  const [lightboxOpen, setLightboxOpen] = useState(false)

  const previewSrc = `/api/tomograms/${encodeURIComponent(sampleId)}/${encodeURIComponent(acquisitionId)}/${encodeURIComponent(tomo.tomogram_id)}/preview.png`
  const ngPath = `/tomograms/${encodeURIComponent(sampleId)}/${encodeURIComponent(acquisitionId)}/${encodeURIComponent(tomo.tomogram_id)}/neuroglancer`

  const shape =
    tomo.image_size_x !== null &&
    tomo.image_size_y !== null &&
    tomo.image_size_z !== null
      ? `${tomo.image_size_x}×${tomo.image_size_y}×${tomo.image_size_z}`
      : null

  const voxel = tomo.voxel_spacing_angstrom ?? tomo.voxel_spacing_angstrom_implied

  const entries: Array<[string, unknown]> = [
    ['Shape', shape],
    ['Voxel spacing (Å)', voxel],
    ['Pipeline', tomo.pipeline],
    ['Software', tomo.software],
    ['Voxel bin', tomo.voxel_bin],
    ['Zarr axes', tomo.zarr_axes],
    ['Zarr scale', tomo.zarr_scale],
    ['Size', formatBytes(tomo.size_bytes)],
  ]

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h6">{tomo.tomogram_id}</Typography>

          <SubEntityBlock title="Tomogram metadata" entries={entries} />

          <Stack spacing={0.5}>
            {tomo.mrc_path ? (
              <PathRow label="MRC" path={tomo.mrc_path} />
            ) : null}
            {tomo.zarr_path ? (
              <PathRow label="Zarr" path={tomo.zarr_path} />
            ) : null}
          </Stack>

          <Box sx={{ position: 'relative', minHeight: 200 }}>
            {imgError ? (
              <EmptyState title="Preview unavailable" />
            ) : (
              <>
                {!imgLoaded ? (
                  <Skeleton
                    variant="rectangular"
                    height={300}
                    sx={{
                      position: 'absolute',
                      inset: 0,
                    }}
                  />
                ) : null}
                <Box
                  component="img"
                  loading="lazy"
                  src={previewSrc}
                  alt={`Preview of ${tomo.tomogram_id}`}
                  onLoad={() => setImgLoaded(true)}
                  onError={() => setImgError(true)}
                  onClick={() => setLightboxOpen(true)}
                  sx={{
                    maxWidth: '100%',
                    cursor: 'pointer',
                    display: imgLoaded ? 'block' : 'block',
                    opacity: imgLoaded ? 1 : 0,
                  }}
                />
              </>
            )}
          </Box>

          <NeuroglancerButton launchPath={ngPath} />
        </Stack>
      </CardContent>
      <Lightbox
        open={lightboxOpen}
        onClose={() => setLightboxOpen(false)}
        src={previewSrc}
        alt={`Preview of ${tomo.tomogram_id}`}
      />
    </Card>
  )
}
