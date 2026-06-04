import { useState } from 'react'
import { Box } from '@mui/material'
import ImageOutlinedIcon from '@mui/icons-material/ImageOutlined'

type Size = number | string

// Shared grey-box placeholder used wherever a representative image is missing
// (samples table, acquisition rows, sample-detail hero). Uses theme tokens
// (`action.hover` / `text.disabled`) rather than literal greys so it tracks
// the palette.
export function ThumbnailPlaceholder(props: {
  width?: Size
  height?: Size
}) {
  const { width = 56, height = 40 } = props
  return (
    <Box
      sx={{
        width,
        height,
        borderRadius: 1,
        bgcolor: 'action.hover',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'text.disabled',
      }}
    >
      <ImageOutlinedIcon fontSize="small" />
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
