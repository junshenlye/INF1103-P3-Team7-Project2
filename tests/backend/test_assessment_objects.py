"""Entity isolation, polymorphic queries and manager-owned scheduling."""
from dataclasses import asdict

import pytest

from src.managers.logic_manager import LogicManager
from src.models.assessments.assessment import Assessment
from src.models.assessments.schedule import Schedule
from src.models.projects.module import Module
from src.models.documents.document import Document
from src.models.documents.source_element import SourceElement


def facts(kind='assessment', week=3, end_week=5):
    return {'key': 'quiz', 'name': 'Quiz', 'kind': kind,
            'week': week, 'end_week': end_week}


def make_assessment(kind='assessment', week=3, end_week=5):
    return LogicManager().create_assessment('a', 'r', 'm', facts(kind, week, end_week),
                                            {'name': ['source']})


def rows(assessment):
    return [{'id': assessment.id, 'result_id': assessment.result_id,
             'module_id': assessment.module_id, 'facts': assessment.facts,
             'evidence': assessment.evidence}]


def module(assessments=()):
    return Module('m', 'p', 'j', 'INF1103', 'inf1103', 6, 0, assessments)


def test_base_requires_concrete_scheduling_behaviour():
    with pytest.raises(TypeError):
        Assessment('a', 'r', 'm', {}, {})


@pytest.mark.parametrize('kind,week,end,span,scheduled,unknown', [
    ('assessment', 3, 5, (3, 5), [3, 4, 5], 0),
    ('assessment', None, None, (None, None), [], 1),
    ('group', None, None, None, [], 0),
])
def test_same_query_supports_ranges_unknown_timing_and_group_totals(kind, week, end, span, scheduled, unknown):
    assessment = make_assessment(kind, week, end)
    before = asdict(assessment)
    assert assessment.scheduling_span() == span
    schedule = LogicManager().build_schedule([module()], rows(assessment), 14, 'p').to_record()
    assert [w['week'] for w in schedule['weeks'] if w['items']] == scheduled
    assert len(schedule['unscheduled']) == unknown
    assert asdict(assessment) == before
    assert len(schedule['weeks']) == 14


def test_module_references_independent_assessments_and_calendar_copies_values():
    assessment = make_assessment()
    aggregate = module((assessment,))
    assert aggregate.get_assessments()[0] is assessment
    schedule = LogicManager().build_schedule([aggregate], rows(assessment), 14, 'p')
    exported = schedule.to_record()
    exported['weeks'][2]['items'][0]['evidence']['name'].append('changed')
    assert assessment.evidence == {'name': ['source']}
    assert exported['weeks'][3]['items'][0]['evidence'] == {'name': ['source']}
    assert schedule.to_record()['weeks'][2]['items'][0]['evidence'] == {'name': ['source']}
    del aggregate
    assert assessment.facts['name'] == 'Quiz'


def test_running_schedule_path_wires_real_module_aggregation():
    grouped, = LogicManager().group_assessments([module()], rows(make_assessment()))
    part, = grouped.get_assessments()
    assert isinstance(part, Assessment) and part.module_id == grouped.id
    del grouped
    assert part.scheduling_span() == (3, 5)


@pytest.mark.parametrize('start,end', [(12, 15), (0, 2), (5, 4), (True, 3), (2, '3')])
def test_invalid_schedule_range_is_atomic(start, end):
    schedule = Schedule('p', 14)
    before = schedule.to_record()
    with pytest.raises(ValueError):
        schedule.add_item({}, start, end)
    assert schedule.to_record() == before


def test_assessment_copies_incoming_and_outgoing_mutable_data():
    own_facts, own_evidence = facts(), {'name': ['source']}
    assessment = LogicManager().create_assessment('a', 'r', 'm', own_facts, own_evidence)
    own_facts['week'] = 14
    own_evidence['name'].clear()
    assessment.facts['week'] = 1
    assessment.evidence['name'].append('bad')
    output = assessment.to_record('INF1103')
    output['evidence']['name'].clear()
    assert assessment.scheduling_span() == (3, 5)
    assert assessment.evidence == {'name': ['source']}


def test_source_element_copies_geometry_at_both_boundaries():
    regions = [{'page': 1, 'bbox': [0, 0, 1, 1]}]
    source = SourceElement('s', 'd', 'parse', 'Quiz', regions, 'paragraph')
    regions[0]['bbox'][0] = 100
    source.regions[0]['bbox'][0] = 200
    source.to_record()['regions'][0]['bbox'][0] = 300
    assert source.regions == [{'page': 1, 'bbox': [0, 0, 1, 1]}]


def test_passive_reference_holders_never_inspect_or_call_their_parts():
    class UnreadablePeer:
        def __getattribute__(self, name):
            raise AssertionError('An entity inspected another entity: ' + name)

        def __repr__(self):
            raise AssertionError('An entity represented another entity.')

        def __eq__(self, other):
            raise AssertionError('An entity compared another entity.')

    from src.models.projects.project import Project
    from src.models.processing.processing_job import ProcessingJob
    from src.models.assessments.individual_assessment import IndividualAssessment
    from src.models.assessments.assessment_group import AssessmentGroup
    for entity_type in (Module, Document, Project, ProcessingJob, SourceElement, Schedule,
                        Assessment, IndividualAssessment, AssessmentGroup):
        assert entity_type.__eq__ is object.__eq__

    peer = UnreadablePeer()
    assert module((peer,)).get_assessments() == (peer,)
    document = Document('d', 'm', 'brief.png', 'image/png', 3, 'hash', 'originals/d', (peer,))
    assert document.get_sources()[0] is peer
    assert module((peer,)) != module((UnreadablePeer(),))
    assert document != Document('d', 'm', 'brief.png', 'image/png', 3, 'hash', 'originals/d', (UnreadablePeer(),))
    assert 'INF1103' in repr(module((peer,))) and 'brief.png' in repr(document)
