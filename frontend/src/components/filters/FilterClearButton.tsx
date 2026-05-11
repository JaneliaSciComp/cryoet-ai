import { Button } from '@mui/material'

type FilterClearButtonProps = {
  onClear: () => void
  disabled?: boolean
}

export function FilterClearButton(props: FilterClearButtonProps) {
  const { onClear, disabled } = props
  return (
    <Button size="small" variant="text" onClick={onClear} disabled={disabled}>
      Clear filters
    </Button>
  )
}
