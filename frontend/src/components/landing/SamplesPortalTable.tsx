import { useMemo } from 'react'
import {
  MaterialReactTable,
  useMaterialReactTable,
  type MRT_ColumnDef,
} from 'material-react-table'
import type { SampleSummary } from '~/types'
import { CustomLink } from '~/components/CustomLink'
import { PreviewThumbnail, thumbnailUrl } from '~/components/common/Thumbnail'
import { AcquisitionsSubTable } from './AcquisitionsSubTable'

const dash = (v: unknown) => (v == null || v === '' ? '—' : String(v))

export function SamplesPortalTable(props: {
  rows: SampleSummary[]
  loading?: boolean
}) {
  const { rows, loading } = props

  const columns = useMemo<MRT_ColumnDef<SampleSummary>[]>(
    () => [
      {
        id: 'thumbnail',
        header: '',
        columnDefType: 'display',
        size: 80,
        Cell: ({ row }) => (
          <PreviewThumbnail src={thumbnailUrl(row.original.thumbnail_path)} />
        ),
      },
      {
        accessorKey: 'sample_id',
        header: 'Sample id',
        minSize: 160,
        Cell: ({ row }) => (
          <CustomLink
            to="/samples/$sampleId"
            params={{ sampleId: row.original.sample_id }}
          >
            {row.original.sample_id}
          </CustomLink>
        ),
      },
      { accessorKey: 'data_source', header: 'Data source' },
      { accessorKey: 'project', header: 'Project' },
      {
        accessorKey: 'type',
        header: 'Type',
        Cell: ({ cell }) => dash(cell.getValue()),
      },
      { accessorKey: 'n_acquisitions', header: 'Acq', size: 80 },
      { accessorKey: 'n_tilt_series', header: 'Tilt', size: 80 },
      { accessorKey: 'n_tomograms', header: 'Tomo', size: 80 },
    ],
    [],
  )

  const table = useMaterialReactTable({
    columns,
    data: rows,
    getRowId: (r) => r.sample_id,
    positionExpandColumn: 'first',
    // MRT wraps the panel in <Collapse mountOnEnter unmountOnExit>, so this
    // component only mounts (and fetches its sample detail) when the row is
    // expanded — acquisitions load lazily on demand, not N fetches up front.
    // Returning a truthy element here (rather than null when collapsed) is
    // what keeps each row's expand button enabled.
    renderDetailPanel: ({ row }) => (
      <AcquisitionsSubTable sampleId={row.original.sample_id} />
    ),
    enableColumnActions: false,
    enableColumnFilters: false,
    enableTopToolbar: false,
    enableDensityToggle: false,
    state: { isLoading: loading },
    initialState: {
      density: 'comfortable',
      pagination: { pageSize: 10, pageIndex: 0 },
    },
    muiTablePaperProps: {
      elevation: 0,
      sx: { border: 1, borderColor: 'divider', borderRadius: 2 },
    },
    muiDetailPanelProps: { sx: { p: 0 } },
  })

  return <MaterialReactTable table={table} />
}
