import { useState, type ReactNode } from 'react'
import { Box, Typography } from '@mui/material'
import ImageOutlinedIcon from '@mui/icons-material/ImageOutlined'

type Size = number | string

// Shared grey-box placeholder used wherever a representative image or viewer is
// missing (samples table, acquisition rows, sample-detail hero, acquisition
// tilt-series slot). Uses theme tokens (`action.hover` / `text.disabled`)
// rather than literal greys so it tracks the palette. Pass `icon` / `label` to
// hint at what will eventually fill the slot (e.g. a tilt-series viewer).
export function ThumbnailPlaceholder(props: {
  width?: Size
  height?: Size
  icon?: ReactNode
  label?: string
}) {
  const { width = 56, height = 40, icon, label } = props
  return (
    <Box
      sx={{
        width,
        height,
        borderRadius: 1,
        bgcolor: 'action.hover',
        display: 'flex',
        flexDirection: 'column',
        gap: 0.5,
        alignItems: 'center',
        justifyContent: 'center',
        color: 'text.disabled',
      }}
    >
      {icon ?? <ImageOutlinedIcon fontSize="small" />}
      {label ? (
        <Typography variant="caption" color="text.disabled">
          {label}
        </Typography>
      ) : null}
    </Box>
  )
}

// Renders an image, falling back to the placeholder when no `src` is given or
// the request fails (e.g. the preview endpoint returns 422 for EER-only tilt
// series). Keeps the same footprint either way so table rows don't jump.
export function PreviewThumbnail(props: {
  src?: string | null
  alt?: string
  width?: Size
  height?: Size
}) {
  const { src, alt = '', width = 56, height = 40 } = props
  const [failed, setFailed] = useState(false)

  if (!src || failed) {
    return <ThumbnailPlaceholder width={width} height={height} />
  }

  return (
    <Box
      component="img"
      src={src}
      alt={alt}
      onError={() => setFailed(true)}
      sx={{
        width,
        height,
        objectFit: 'cover',
        borderRadius: 1,
        display: 'block',
        bgcolor: 'action.hover',
      }}
    />
  )
}
