import { useMemo } from 'react'
import {
  MaterialReactTable,
  useMaterialReactTable,
  type MRT_ColumnDef,
} from 'material-react-table'
import type { AcquisitionOut } from '~/types'
import { CustomLink } from '~/components/CustomLink'
import { PreviewThumbnail, tomogramThumbnailUrl, acquisitionRepTomogramId } from '~/components/common/Thumbnail'

// Mirrors the API's `n_tomograms` semantics: raw + post-processed combined.
function tomogramCount(a: AcquisitionOut): number {
  return (a.raw_tomogram ? 1 : 0) + a.post_processed_tomograms.length
}

function acquisitionPreviewSrc(sampleId: string, a: AcquisitionOut): string | null {
  const repId = acquisitionRepTomogramId(a)
  return repId ? tomogramThumbnailUrl(sampleId, a.acquisition_id, repId) : null
}

export function SampleAcquisitionsTable(props: {
  sampleId: string
  acquisitions: AcquisitionOut[]
}) {
  const { sampleId, acquisitions } = props

  const columns = useMemo<MRT_ColumnDef<AcquisitionOut>[]>(
    () => [
      {
        id: 'thumbnail',
        header: '',
        columnDefType: 'display',
        enableSorting: false,
        size: 140,
        Cell: ({ row }) => (
          <PreviewThumbnail
            src={acquisitionPreviewSrc(sampleId, row.original)}
            alt={`${row.original.acquisition_id} preview`}
            width={96}
            height={64}
          />
        ),
      },
      {
        accessorKey: 'acquisition_id',
        header: 'Acquisition id',
        minSize: 160,
        Cell: ({ row }) => (
          <CustomLink
            to="/acquisitions/$acquisitionId"
            params={{ acquisitionId: row.original.acquisition_id }}
            search={{ sampleId }}
          >
            {row.original.acquisition_id}
          </CustomLink>
        ),
      },
      {
        id: 'n_tilt_series',
        header: 'Tilt series',
        accessorFn: (a) => a.tilt_series.length,
        size: 120,
      },
      {
        id: 'n_tomograms',
        header: 'Tomograms',
        accessorFn: tomogramCount,
        size: 120,
      },
      {
        id: 'n_annotations',
        header: 'Annotations',
        accessorFn: (a) => a.annotations.length,
        size: 120,
      },
    ],
    [sampleId],
  )

  const table = useMaterialReactTable({
    columns,
    data: acquisitions,
    getRowId: (a) => a.acquisition_id,
    enableSorting: true,
    enableColumnActions: false,
    enableColumnFilters: false,
    enableTopToolbar: false,
    enableBottomToolbar: false,
    enableDensityToggle: false,
    enablePagination: false,
    initialState: { density: 'comfortable' },
    muiTablePaperProps: {
      elevation: 0,
      sx: { border: 1, borderColor: 'divider', borderRadius: 2 },
    },
    localization: { noRecordsToDisplay: 'No acquisitions for this sample.' },
  })

  return <MaterialReactTable table={table} />
}
