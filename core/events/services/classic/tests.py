from unittest import TestCase, mock
import os
from datetime import datetime
from contextlib import contextmanager
import json

from sqlalchemy import TypeDecorator, func, String, Column
from sqlalchemy import JSON, DateTime, ForeignKey
from sqlalchemy.types import NullType
from sqlalchemy.orm import relationship
from sqlalchemy.ext.indexable import index_property
from flask import Flask

from events.domain.submission import License, Submission
from events.domain.event import CreateSubmissionEvent, UpdateMetadataEvent, \
    FinalizeSubmissionEvent, SetPrimaryClassificationEvent, \
    AddSecondaryClassificationEvent
from events.domain.agent import User
from events.services import classic


class SQLiteJson(TypeDecorator):
    """
    SQLite-friendly implementation of a JSON type.

    Adapted from https://bitbucket.org/zzzeek/sqlalchemy/issues/3850/request-sqlite-json1-ext-support.
    """

    impl = String

    class Comparator(String.Comparator):
        def __getitem__(self, index):
            if isinstance(index, tuple):
                index = "$%s" % (
                    "".join([
                        "[%s]" % elem if isinstance(elem, int)
                        else '."%s"' % elem for elem in index
                    ])
                )
            elif isinstance(index, int):
                index = "$[%s]" % index
            else:
                index = '$."%s"' % index

            # json_extract does not appear to return JSON sub-elements
            # which is weird.
            return func.json_extract(self.expr, index, type_=NullType)

    comparator_factory = Comparator

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = json.loads(value)
        return value


@contextmanager
def in_memory_db():
    app = Flask('foo')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    with app.app_context():
        classic.init_app(app)
        classic.create_all()
        try:
            yield classic.current_session()
        except Exception:
            raise
        finally:
            classic.drop_all()


class MockEvent(classic.Base):
    """SQLite-friendly alternative for Event model."""

    __tablename__ = 'event'

    event_id = Column(String(40), primary_key=True)
    event_type = Column(String(255))
    proxy = Column(SQLiteJson)
    proxy_id = index_property('proxy', 'agent_identifier')

    creator = Column(SQLiteJson)
    creator_id = index_property('creator', 'agent_identifier')

    created = Column(DateTime)
    data = Column(SQLiteJson)
    submission_id = Column(
        ForeignKey('arXiv_submissions.submission_id'),
        index=True
    )
    submission = relationship("Submission")


class TestGetLicenses(TestCase):
    """Test :func:`.classic.get_licenses`."""

    # @mock.patch('events.services.classic.JSON', new=SQLiteJson)
    @mock.patch('events.services.classic._declare_event')
    def test_get_all_active_licenses(self, mock__declare_event):
        """Return a :class:`.License` for each active license in the db."""
        mock__declare_event.return_value = MockEvent

        with in_memory_db() as session:
            session.add(classic.models.License(
                name="http://arxiv.org/licenses/assumed-1991-2003",
                sequence=9,
                label="Assumed arXiv.org perpetual, non-exclusive license to",
                active=0
            ))
            session.add(classic.models.License(
                name="http://creativecommons.org/licenses/publicdomain/",
                sequence=4,
                label="Creative Commons Public Domain Declaration",
                active=1
            ))
            session.commit()
            licenses = classic.get_licenses()

        self.assertEqual(len(licenses), 1,
                         "Only the active license should be returned.")
        self.assertIsInstance(licenses[0], License,
                              "Should return License instances.")
        self.assertEqual(licenses[0].uri,
                         "http://creativecommons.org/licenses/publicdomain/",
                         "Should use name column to populate License.uri")
        self.assertEqual(licenses[0].name,
                         "Creative Commons Public Domain Declaration",
                         "Should use label column to populate License.name")


class TestStoreEvents(TestCase):
    """Test :func:`.classic.store_events`."""

    @mock.patch('events.services.classic._declare_event')
    def test_store_event(self, mock__declare_event):
        """Store a single event."""
        mock__declare_event.return_value = MockEvent

        with in_memory_db() as session:
            user = User(12345)
            ev = CreateSubmissionEvent(creator=user)
            submission = ev.apply()
            submission = classic.store_events(ev, submission=submission)

            db_submission = session.query(classic.models.Submission)\
                .get(submission.submission_id)

        self.assertEqual(db_submission.submission_id, submission.submission_id,
                         "The submission should be updated with the PK id.")
        self.assertEqual(db_submission.submitter_id,
                         submission.creator.native_id,
                         "The native ID of the creator should be used")
        self.assertEqual(db_submission.status, db_submission.NOT_SUBMITTED,
                         "Submission in database should be in status 0 (not"
                         " submitted) by default.")

    @mock.patch('events.services.classic._declare_event')
    def test_store_events_with_metadata(self, mock__declare_event):
        """Store events and attendant submission with metadata."""
        mock__declare_event.return_value = MockEvent

        metadata = {
            'title': 'foo title',
            'abstract': 'very abstract',
            'comments': 'indeed',
            'msc_class': 'foo msc',
            'acm_class': 'computer-y',
            'doi': '10.01234/5678',
            'journal_ref': 'Nature 1: 1',
            'authors': ['Joe Bloggs and friends']
        }
        with in_memory_db() as session:
            user = User(12345)
            ev = CreateSubmissionEvent(creator=user)
            ev2 = UpdateMetadataEvent(creator=user,
                                      metadata=list(metadata.items()))

            submission = ev.apply()
            submission = ev2.apply(submission)
            submission = classic.store_events(ev, ev2, submission=submission)

            db_submission = session.query(classic.models.Submission)\
                .get(submission.submission_id)

            db_events = session.query(classic.Event).all()

        for key, value in metadata.items():
            if key == 'authors':
                continue
            self.assertEqual(getattr(db_submission, key), value,
                             f"The value of {key} should be {value}")
        self.assertEqual(db_submission.authors,
                         submission.metadata.authors_canonical,
                         "The canonical author string should be used to"
                         " update the submission in the database.")

        self.assertEqual(len(db_events), 2, "Two events should be stored")
        for db_event in db_events:
            self.assertEqual(db_event.submission_id, submission.submission_id,
                             "The submission id should be set")

    @mock.patch('events.services.classic._declare_event')
    def test_store_events_with_finalized_submission(self, mock__declare_event):
        """Store events and a finalized submission."""
        mock__declare_event.return_value = MockEvent

        with in_memory_db() as session:
            user = User(12345)
            ev = CreateSubmissionEvent(creator=user)
            ev2 = FinalizeSubmissionEvent(creator=user)
            submission = ev.apply()
            submission = ev2.apply(submission)
            submission = classic.store_events(ev, ev2, submission=submission)

            db_submission = session.query(classic.models.Submission)\
                .get(submission.submission_id)
            db_events = session.query(classic.Event).all()

        self.assertEqual(db_submission.submission_id, submission.submission_id,
                         "The submission should be updated with the PK id.")
        self.assertEqual(len(db_events), 2, "Two events should be stored")
        for db_event in db_events:
            self.assertEqual(db_event.submission_id, submission.submission_id,
                             "The submission id should be set")

    @mock.patch('events.services.classic._declare_event')
    def test_store_events_with_classification(self, mock__declare_event):
        """Store events including classification."""
        mock__declare_event.return_value = MockEvent

        user = User(12345)
        ev = CreateSubmissionEvent(creator=user)
        ev2 = SetPrimaryClassificationEvent(creator=user,
                                            category='physics.soc-ph')
        ev3 = AddSecondaryClassificationEvent(creator=user,
                                              category='physics.acc-ph')
        submission = ev.apply()
        submission = ev2.apply(submission)
        submission = ev3.apply(submission)

        with in_memory_db() as session:
            submission = classic.store_events(ev, ev2, ev3,
                                              submission=submission)

            db_submission = session.query(classic.models.Submission)\
                .get(submission.submission_id)
            db_events = session.query(classic.Event).all()

        self.assertEqual(db_submission.submission_id, submission.submission_id,
                         "The submission should be updated with the PK id.")
        self.assertEqual(len(db_events), 3, "Three events should be stored")
        for db_event in db_events:
            self.assertEqual(db_event.submission_id, submission.submission_id,
                             "The submission id should be set")
        self.assertEqual(len(db_submission.categories), 2,
                         "Two category relations should be set")
        self.assertEqual(db_submission.primary_classification.category,
                         submission.primary_classification.category,
                         "Primary classification should be set.")


class TestGetSubmission(TestCase):
    """Test :func:`.classic.get_submission`."""

    @mock.patch('events.services.classic._declare_event')
    def test_get_submission(self, mock__declare_event):
        """Get a single submission from the classic database."""
        mock__declare_event.return_value = MockEvent

        sample_submission = {
          "doi": "10.1063/foo123",
          "proxy": None,
          "stage": 0,
          "title": "Achieving Anisotropy in Foo",
          "status": 27,
          "viewed": 0,
          "authors": "Liang Bloggs, Jane Doe, and Bob Dole",
          "created": datetime(year=2011, month=6, day=16, hour=14, minute=51, second=9),
          "updated": datetime(year=2011, month=7, day=2, hour=3, minute=37, second=11),
          "abstract": "We show that foo",
          "sword_id": None,
          "userinfo": 0,
          "acm_class": None,
          "is_author": 0,
          "msc_class": None,
          "report_num": None,
          "document_id": 12345,
          "journal_ref": "Appl. Foo. Lett. 1, 2 (2011)",
          "source_size": 0,
          "submit_time": datetime(year=2011, month=7, day=2, hour=3, minute=37, second=12),
          "agree_policy": 0,
          "doc_paper_id": "1234.5678",
          "is_withdrawn": 0,
          "must_process": 1,
          "release_time": None,
          "source_flags": None,
          "submitter_id": 9876,
          "source_format": None,
          "sticky_status": None,
          "submission_id": 59944,
          "has_pilot_data": None,
          "submitter_name": "Bob Dole",
          "submitter_email": "bob@dole.foo",
          "type": "new"
        }

        with in_memory_db() as session:
            session.add(classic.models.Submission(
                **sample_submission
            ))
            session.commit()
            submission = classic.get_submission(59944)
        self.assertIsInstance(submission, Submission)
