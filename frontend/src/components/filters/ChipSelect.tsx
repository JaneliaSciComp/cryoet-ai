import { Autocomplete, TextField } from '@mui/material'

type ChipSelectProps = {
  label: string
  options: ReadonlyArray<string>
  value: Array<string>
  onChange: (next: Array<string>) => void
}

export function ChipSelect(props: ChipSelectProps) {
  const { label, options, value, onChange } = props
  if (options.length === 0) return null
  return (
    <Autocomplete
      multiple
      options={options as Array<string>}
      value={value}
      onChange={(_, v) => onChange(v)}
      renderInput={(params) => (
        <TextField {...params} label={label} size="small" />
      )}
    />
  )
}

type NumberChipSelectProps = {
  label: string
  options: ReadonlyArray<number>
  value: Array<number>
  onChange: (next: Array<number>) => void
}

export function NumberChipSelect(props: NumberChipSelectProps) {
  const { label, options, value, onChange } = props
  if (options.length === 0) return null
  const stringOptions = options.map((n) => String(n))
  const stringValue = value.map((n) => String(n))
  return (
    <Autocomplete
      multiple
      options={stringOptions}
      value={stringValue}
      onChange={(_, v) =>
        onChange(v.map((s) => Number(s)).filter((n) => Number.isFinite(n)))
      }
      renderInput={(params) => (
        <TextField {...params} label={label} size="small" />
      )}
    />
  )
}
