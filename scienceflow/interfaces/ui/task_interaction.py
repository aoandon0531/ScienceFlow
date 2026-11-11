"""Recognize explicit chat task boundaries while retaining one conversation."""

import asyncio
from uuid import uuid4

from inquirycraft.tui import DelegatingTuiInterceptor

from scienceflow.interfaces.ui.instruction_author import author_task_instructions
from scienceflow.research.onboarding.support.task_instructions import save_task_instructions


class TaskInstructionInteraction(DelegatingTuiInterceptor):
    def __init__(self, delegate):
        super().__init__(delegate)
        self._instruction_job = None
        self._forwarding = False

    async def preprocess_input(self, text, host):
        preprocess = getattr(self.delegate, "preprocess_input", None)
        if callable(preprocess) and await preprocess(text, host):
            return True
        if (
            not self._forwarding and self._instruction_job
            and not self._instruction_job.done() and not text.lstrip().startswith("/")
        ):
            await host.notice("Finish or cancel the active request before submitting another task.")
            return True
        return False

    async def try_handle(self, text, host):
        if self._forwarding:
            return False
        if await self.delegate.try_handle(text, host):
            return True
        if not text.strip() or text.lstrip().startswith("/") or host.busy:
            return False
        activate = getattr(getattr(host, "runtime", None), "activate_task", None)
        if self.delegate.session is not None or not callable(activate):
            return False
        self._instruction_job = asyncio.create_task(self._handle_chat(text, host))
        return True

    async def _handle_chat(self, text, host):
        runtime = host.runtime
        try:
            echo = getattr(host, "echo_user", None)
            submit = getattr(host, "submit_text", None)
            if not callable(submit) and callable(echo):
                await echo(text)
            current = runtime.active_task
            authored = await author_task_instructions(
                self.delegate, host, text, facts={}, current=current, detect=True
            )
            if authored.action != "keep":
                instance_id = current.path.parent.name if authored.action == "update" else uuid4().hex
                workspace = current.path.parents[3] if authored.action == "update" else self.delegate.workspace
                snapshot = await asyncio.to_thread(
                    save_task_instructions, instance_id, workspace, authored.markdown
                )
                runtime.activate_task(snapshot, authored.title)
                await host.notice(
                    f"Active task instructions: {snapshot.path} (sha256={snapshot.digest[:12]})"
                )
            if callable(submit):
                self._forwarding = True
                try:
                    accepted = await submit(text)
                    if accepted and callable(getattr(host, "query_one", None)):
                        # Match the pinned TUI editor's ordinary submission history.
                        host.query_one("#prompt").remember_submission(text)
                finally:
                    self._forwarding = False
            else:
                await host.run_host_task(text, show_response=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await host.notice(f"Task request could not complete: {type(exc).__name__}: {exc}")
        finally:
            self._instruction_job = None

    async def aclose(self):
        job = self._instruction_job
        if job and not job.done():
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
        await self.delegate.aclose()
