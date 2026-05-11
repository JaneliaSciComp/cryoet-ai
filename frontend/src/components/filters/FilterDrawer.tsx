import { useEffect, useRef, useState } from 'react'
import {
  Box,
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
} from '@mui/material'
import type { FiltersOptionsOut, RangeOut } from '~/types'
import type { SamplesSearchParams } from '~/routes/samples'
import { useDebounce } from '~/hooks/useDebounce'
import { ChipSelect, NumberChipSelect } from './ChipSelect'
import { RangeSlider } from './RangeSlider'
import { FilterClearButton } from './FilterClearButton'

type FilterDrawerProps = {
  options: FiltersOptionsOut
  initial: Partial<SamplesSearchParams>
  onChange: (next: Partial<SamplesSearchParams>) => void
  onCopyUrl: (params: Partial<SamplesSearchParams>) => void
}

type TriState = '' | 'true' | 'false'

function rangeHasBounds(r: RangeOut): r is { min: number; max: number } {
  return (
    r.min !== null &&
    r.max !== null &&
    Number.isFinite(r.min) &&
    Number.isFinite(r.max)
  )
}

export function FilterDrawer(props: FilterDrawerProps) {
  const { options, initial, onChange, onCopyUrl } = props
  const [state, setState] = useState<Partial<SamplesSearchParams>>(initial)
  const debounced = useDebounce(state, 300)
  const firstRunRef = useRef(false)

  useEffect(() => {
    if (!firstRunRef.current) {
      firstRunRef.current = true
      return
    }
    onChange(debounced)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced])

  const update = (patch: Partial<SamplesSearchParams>) =>
    setState((prev) => ({ ...prev, ...patch }))

  const hasTomogramsValue: TriState =
    state.has_tomograms === true
      ? 'true'
      : state.has_tomograms === false
        ? 'false'
        : ''

  return (
    <Box sx={{ padding: 2 }}>
      <Stack spacing={2}>
        <TextField
          label="Search"
          size="small"
          value={state.q ?? ''}
          onChange={(e) =>
            update({ q: e.target.value === '' ? undefined : e.target.value })
          }
        />

        {options.projects.length > 0 && (
          <FormControl size="small" fullWidth>
            <InputLabel>Project</InputLabel>
            <Select
              label="Project"
              value={state.project ?? ''}
              onChange={(e) =>
                update({
                  project: e.target.value === '' ? undefined : e.target.value,
                })
              }
            >
              <MenuItem value="">Any</MenuItem>
              {options.projects.map((p) => (
                <MenuItem key={p} value={p}>
                  {p}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        )}

        {options.data_sources.length > 0 && (
          <FormControl size="small" fullWidth>
            <InputLabel>Data source</InputLabel>
            <Select
              label="Data source"
              value={state.data_source ?? ''}
              onChange={(e) =>
                update({
                  data_source:
                    e.target.value === '' ? undefined : e.target.value,
                })
              }
            >
              <MenuItem value="">Any</MenuItem>
              {options.data_sources.map((d) => (
                <MenuItem key={d} value={d}>
                  {d}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        )}

        <ChipSelect
          label="Type"
          options={options.types}
          value={state.type ?? []}
          onChange={(v) => update({ type: v.length === 0 ? undefined : v })}
        />

        <ChipSelect
          label="Microscope"
          options={options.microscopes}
          value={state.microscope ?? []}
          onChange={(v) =>
            update({ microscope: v.length === 0 ? undefined : v })
          }
        />

        <NumberChipSelect
          label="Voltage"
          options={options.voltages}
          value={state.voltage ?? []}
          onChange={(v) => update({ voltage: v.length === 0 ? undefined : v })}
        />

        <ChipSelect
          label="Camera"
          options={options.cameras}
          value={state.camera ?? []}
          onChange={(v) => update({ camera: v.length === 0 ? undefined : v })}
        />

        <ChipSelect
          label="Image format"
          options={options.image_formats}
          value={state.image_format ?? []}
          onChange={(v) =>
            update({ image_format: v.length === 0 ? undefined : v })
          }
        />

        {rangeHasBounds(options.pixel_size) && (
          <RangeSlider
            label="Pixel size"
            min={options.pixel_size.min}
            max={options.pixel_size.max}
            value={[
              state.pixel_size_min ?? null,
              state.pixel_size_max ?? null,
            ]}
            onChange={([lo, hi]) =>
              update({ pixel_size_min: lo, pixel_size_max: hi })
            }
          />
        )}

        {rangeHasBounds(options.voxel_spacing) && (
          <RangeSlider
            label="Voxel spacing"
            min={options.voxel_spacing.min}
            max={options.voxel_spacing.max}
            value={[
              state.voxel_spacing_min ?? null,
              state.voxel_spacing_max ?? null,
            ]}
            onChange={([lo, hi]) =>
              update({ voxel_spacing_min: lo, voxel_spacing_max: hi })
            }
          />
        )}

        {rangeHasBounds(options.n_tilts) && (
          <RangeSlider
            label="Number of tilts"
            min={options.n_tilts.min}
            max={options.n_tilts.max}
            step={1}
            value={[state.n_tilts_min ?? null, state.n_tilts_max ?? null]}
            onChange={([lo, hi]) =>
              update({ n_tilts_min: lo, n_tilts_max: hi })
            }
          />
        )}

        <FormControl size="small" fullWidth>
          <InputLabel>Has tomograms</InputLabel>
          <Select
            label="Has tomograms"
            value={hasTomogramsValue}
            onChange={(e) => {
              const v = e.target.value as TriState
              update({
                has_tomograms:
                  v === 'true' ? true : v === 'false' ? false : undefined,
              })
            }}
          >
            <MenuItem value="">Any</MenuItem>
            <MenuItem value="true">Yes</MenuItem>
            <MenuItem value="false">No</MenuItem>
          </Select>
        </FormControl>

        <Stack direction="row" spacing={1} justifyContent="space-between">
          <FilterClearButton onClear={() => setState({})} />
          <Button
            size="small"
            variant="outlined"
            onClick={() => onCopyUrl(state)}
          >
            Copy filter URL
          </Button>
        </Stack>
      </Stack>
    </Box>
  )
}
