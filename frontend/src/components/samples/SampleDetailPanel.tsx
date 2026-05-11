import { Stack } from '@mui/material'
import {
  useSampleDetailQuery,
  useSampleWarningsQuery,
} from '~/utils/queryOptions'
import { SampleHeader } from './SampleHeader'
import { SubEntityBlock } from './SubEntityBlock'
import { WarningList } from './WarningList'
import { AcquisitionCard } from './AcquisitionCard'
import type {
  AunpOut,
  ChromatinOut,
  FreezingOut,
  MillingOut,
  SimulationOut,
  SynapseOut,
} from '~/types'

type SampleDetailPanelProps = {
  sampleId: string
}

function chromatinEntries(c: ChromatinOut): Array<[string, unknown]> {
  return [
    ['Substrate', c.substrate],
    ['Linker length (bp)', c.linker_length_bp],
    ['Linker pattern', c.linker_pattern],
    ['Linker distribution', c.linker_distribution],
    ['Buffer', c.buffer],
    ['PTM', c.ptm],
    ['Histone variants', c.histone_variants],
    ['Transcription factors', c.transcription_factors],
    ['Nucleosome count', c.nucleosome_count],
    ['DNA length (bp)', c.dna_length_bp],
    ['Nucleosome (µM)', c.nucleosome_uM],
    ['Sequence identity', c.sequence_identity],
    ['Nucleosome footprint', c.nucleosome_footprint],
    ['Linker length fraction', c.linker_length_fraction],
  ]
}

function synapseEntries(s: SynapseOut): Array<[string, unknown]> {
  return [
    ['Label target', s.label_target],
    ['Label strategy', s.label_strategy],
  ]
}

function simulationEntries(s: SimulationOut): Array<[string, unknown]> {
  return [['Dataset type', s.dataset_type]]
}

function freezingEntries(f: FreezingOut): Array<[string, unknown]> {
  return [
    ['Grid type', f.grid_type],
    ['Cryoprotectant', f.cryoprotectant],
    ['Method', f.method],
    ['Planchette size', f.planchette_size],
    ['Spacer thickness', f.spacer_thickness],
  ]
}

function millingEntries(m: MillingOut): Array<[string, unknown]> {
  return [
    ['Scheme', m.scheme],
    ['Date', m.date],
  ]
}

function aunpEntries(a: AunpOut): Array<[string, unknown]> {
  return [
    ['Ordinal', a.ordinal],
    ['Size (nm)', a.size_nm],
    ['Type', a.type],
    ['Fluorophore', a.fluorophore],
    [
      'Concentration',
      a.concentration_value !== null && a.concentration_unit
        ? `${a.concentration_value} ${a.concentration_unit}`
        : (a.concentration_value ?? null),
    ],
    ['Conjugation', a.conjugation],
    ['Conjugation target', a.conjugation_target],
    ['Notes', a.notes],
  ]
}

export function SampleDetailPanel(props: SampleDetailPanelProps) {
  const { sampleId } = props
  const { data: sample } = useSampleDetailQuery(sampleId)
  const { data: warnings } = useSampleWarningsQuery(sampleId)

  return (
    <Stack spacing={3} sx={{ padding: 2 }}>
      <SampleHeader sample={sample} warningCount={warnings.length} />
      <WarningList warnings={warnings} />

      {sample.description ? (
        <SubEntityBlock
          title="Description"
          entries={[['Description', sample.description]]}
        />
      ) : null}

      {sample.cell_type ? (
        <SubEntityBlock
          title="Cell type"
          entries={[['Cell type', sample.cell_type]]}
        />
      ) : null}

      {sample.chromatin ? (
        <SubEntityBlock
          title="Chromatin"
          entries={chromatinEntries(sample.chromatin)}
        />
      ) : null}

      {sample.synapse ? (
        <SubEntityBlock
          title="Synapse"
          entries={synapseEntries(sample.synapse)}
        />
      ) : null}

      {sample.simulation ? (
        <SubEntityBlock
          title="Simulation"
          entries={simulationEntries(sample.simulation)}
        />
      ) : null}

      {sample.freezing ? (
        <SubEntityBlock
          title="Freezing"
          entries={freezingEntries(sample.freezing)}
        />
      ) : null}

      {sample.milling ? (
        <SubEntityBlock
          title="Milling"
          entries={millingEntries(sample.milling)}
        />
      ) : null}

      {sample.aunp.map((a) => (
        <SubEntityBlock
          key={a.ordinal}
          title={`AuNP #${a.ordinal}`}
          entries={aunpEntries(a)}
        />
      ))}

      {sample.acquisitions.map((acq) => (
        <AcquisitionCard
          key={acq.acquisition_id}
          sampleId={sample.sample_id}
          acq={acq}
        />
      ))}
    </Stack>
  )
}
