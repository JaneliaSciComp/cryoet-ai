import { Button, Tooltip } from '@mui/material'

interface NeuroglancerButtonProps {
  // Neuroglancer viewer URL for this tomogram/annotation. How this link is
  // constructed is still TBD, so callers pass `null` for now and the button
  // renders disabled with an explanatory tooltip.
  url?: string | null
  label?: string
}

// Button-styled link to open a tomogram or annotation in Neuroglancer. Shared
// by both the tomogram rows and the nested annotation rows. Until the link
// scheme is settled, an absent `url` renders a disabled button so the affordance
// is visible without dead-linking.
export function NeuroglancerButton(props: NeuroglancerButtonProps) {
  const { url, label = 'View in Neuroglancer' } = props

  if (!url) {
    return (
      <Tooltip title="Neuroglancer link coming soon">
        {/* span wrapper so the tooltip still fires on the disabled button */}
        <span>
          <Button variant="contained" size="small" disabled>
            {label}
          </Button>
        </span>
      </Tooltip>
    )
  }

  return (
    <Button
      variant="contained"
      size="small"
      href={url}
      target="_blank"
      rel="noopener noreferrer"
    >
      {label}
    </Button>
  )
}
