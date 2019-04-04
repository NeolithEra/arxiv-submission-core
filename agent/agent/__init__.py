"""
Orchestrates backend processes based on rules triggered by submission events.

The primary concerns of the agent are:

- Orchestrating automated processes in support of submission and moderation.
- KEeping track of what processes have been carried out on a submission, and
  the outcomes of those processes.
- Providing a framework for defining conditions under which processes should be
  carried out.

In addition, we anticipate future development of:

- Interfaces for administrators to monitor submission-related processes, and
  to start processes manually.
- A metrics endpoint for Prometheus, to expose process performance/rates.
- Interfaces for administrators to define processing rules.

Conceptual overview
===================

A **process** is a set of one or more related steps that should be carried out
in order, usually focusing on a single submission. Steps are small units of
work with a specific objective, such as getting a resource from a service or
applying a policy. If a step in a process fails, the subsequent steps are not
carried out. Examples of processes include running the autoclassifier and
annotating a submission with the results, and placing submissions on hold when
they exceed size limits.

Processes are implemented by defining a class that inherits from
:class:`.Process`\.

A **rule** defines the circumstances under which a process should be carried
out. Specifically, a rule is associated with a particular type of event, and a
function that determines whether the process should be carried out based on the
event properties and/or the state of the submission.

Rules are implemented by instantiating :class:`.Rule` in :mod:`.rules`.

An **event** is a specific mutation of a submission by an actor at a particular
point in time. See :mod:`arxiv.submission` for an overview of the event model
used in the submission system.

Events are implemented by defining an :class:`.Event` class in
:mod:`arxiv.submission`, and emitted via :func:`arxiv.submission.core.save`.

Architectural overview
======================

Context
-------
The agent operates within the scope of the submission system.

.. _figure-submission-agent-context:

.. figure:: _static/diagrams/submission-agent-context.png
   :width: 600px

   System context for the arXiv submission agent.

The submission agent consumes submission events generated by other applications
running in the submission system, such as the submission UI, via the
``SubmissionEvents`` Kinesis stream. The agent uses the :mod:`arxiv.submission`
package to generate new events, which involves writing to the submission
database and putting records on the ``SubmissionEvents`` Kinesis stream.

In carrying out processes, the agent makes requests to backend services in the
submission system, such as the plain text extraction service, file management
service, etc.

Containers
----------
The submission agent is comprised of four containers that are deployed and
scaled more or less independently.

.. _figure-submission-agent-containers:

.. figure:: _static/diagrams/submission-agent-containers.png
   :width: 600px

   Containers within the arXiv submission agent.

The :mod:`agent.consumer` is a single-threaded process that consumes
notifications about events on the ``SubmissionEvents`` Kinesis stream. It is
implemented on top of :mod:`arxiv.integration.kinesis`. The agent relies
on a database for checkpointing its progress in the stream, and for
commemorating process-relevant submission events. The agent dispatches
steps in triggered processes to be carried out by the :mod:`agent.worker`.

The agent database is a MariaDB SQL database used by the consumer. It stores
checkpoints, process-relevant submission events, and (future) configurations
for user-defined rules.

The :mod:`agent.worker` is an horizontally-scalable `Celery
<http://www.celeryproject.org/>`_ worker that carries out the steps of
processes. These tasks are dispatched by the :mod:`agent.consumer` via a
Redis in-memory key-value store. The worker is responsible for calling backend
services as it carries out its work.

"""
from . import process, rules, runner, consumer, worker, factory


# Prepare all Process types for asynchronous execution.
for process_type in process.Process.__subclasses__():
    runner.AsyncProcessRunner.prepare(process_type)