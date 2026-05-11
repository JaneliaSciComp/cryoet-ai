import { Box } from '@mui/material'
import { DataGrid } from '@mui/x-data-grid'
import type { GridColDef, GridRowSelectionModel } from '@mui/x-data-grid'
import type { SampleSummary } from '~/types'

type SamplesTableProps = {
  rows: SampleSummary[]
  selectedId?: string
  onSelect: (id: string) => void
  loading?: boolean
}

const columns: GridColDef<SampleSummary>[] = [
  { field: 'project', headerName: 'Project', flex: 1, minWidth: 120 },
  { field: 'sample_id', headerName: 'Sample', flex: 1.5, minWidth: 160 },
  { field: 'type', headerName: 'Type', flex: 0.8, minWidth: 100 },
  {
    field: 'n_acquisitions',
    headerName: 'Acq',
    type: 'number',
    width: 80,
  },
  {
    field: 'n_tilt_series',
    headerName: 'Tilt',
    type: 'number',
    width: 80,
  },
  {
    field: 'n_tomograms',
    headerName: 'Tomo',
    type: 'number',
    width: 80,
  },
  {
    field: 'warning_count',
    headerName: 'Warn',
    type: 'number',
    width: 80,
  },
]

export function SamplesTable(props: SamplesTableProps) {
  const { rows, selectedId, onSelect, loading } = props

  const selectionModel: GridRowSelectionModel = selectedId ? [selectedId] : []

  return (
    <Box sx={{ height: '100%', width: '100%' }}>
      <DataGrid<SampleSummary>
        rows={rows}
        columns={columns}
        getRowId={(r) => r.sample_id}
        density="compact"
        disableMultipleRowSelection
        rowSelectionModel={selectionModel}
        onRowSelectionModelChange={(model) => {
          const ids = model as readonly string[]
          const id = ids[0]
          if (id && id !== selectedId) onSelect(id)
        }}
        hideFooterSelectedRowCount
        loading={loading}
      />
    </Box>
  )
}
