import { useState, type ReactNode } from 'react'
import { IconButton, Tooltip } from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import CheckIcon from '@mui/icons-material/Check'

interface CopyIconButtonProps {
  // Text written to the clipboard on click.
  text: string
  // Tooltip describing the action (e.g. "Copy path", "Copy Fileglancer link").
  tooltip: string
  // Optional custom resting icon; defaults to the copy glyph.
  icon?: ReactNode
  // Tooltip shown briefly after a successful copy.
  copiedTooltip?: string
  size?: 'small' | 'medium'
}

export function CopyIconButton(props: CopyIconButtonProps) {
  const {
    text,
    tooltip,
    icon,
    copiedTooltip = 'Copied!',
    size = 'small',
  } = props
  const [copied, setCopied] = useState(false)

  async function handleClick() {
    if (typeof navigator === 'undefined' || !navigator.clipboard) return
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Swallow clipboard errors silently — the user can retry.
    }
  }

  return (
    <Tooltip title={copied ? copiedTooltip : tooltip}>
      <IconButton aria-label={tooltip} size={size} onClick={handleClick}>
        {copied ? (
          <CheckIcon fontSize="small" />
        ) : (
          (icon ?? <ContentCopyIcon fontSize="small" />)
        )}
      </IconButton>
    </Tooltip>
  )
}
