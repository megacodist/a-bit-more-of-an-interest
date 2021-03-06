import asyncio
from concurrent.futures import Future
from datetime import timedelta
import logging
from queue import Empty, Queue
import sys
from threading import Lock, Thread
from time import perf_counter
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Iterable, Mapping, Optional

import aiohttp
import attrs


# Defining og demanding types...
@attrs.define
class ProgInfo:
    nFinished: int
    total: int


class HttpStressTest(Thread):
    def __init__(
            self,
            group: None = None,
            target: Callable[..., Any] | None = None,
            name: str | None = None,
            args: Iterable[Any] = (),
            kwargs: Mapping[str, Any] | None = {},
            *,
            daemon: bool | None = None
            ) -> None:
        super().__init__(
            group,
            target,
            name,
            args,
            kwargs,
            daemon=daemon)

        self._running = True
        self._TIME_INTRVL = 0.1

    def run(self) -> None:
        # Changing default event loop from Proactor to Selector on Windows
        # OS and Python 3.8+...
        if sys.platform.startswith('win'):
            if sys.version_info[:2] >= (3, 8,):
                asyncio.set_event_loop_policy(
                    asyncio.WindowsSelectorEventLoopPolicy())

        while self._running:
            try:
                # Setting up the asyncio event loop...
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
                self.loop.run_forever()
            # Catching asyncio-related errors here...
            finally:
                self.loop.close()

    def close(self) -> None:
        # Because we definitely call this method from a thread other than
        # the thread initiated by run method, we call
        # self.loop.call_soon_threadsafe(self.loop.stop). But if we were
        # on the same thread, we must have called self.loop.stop()
        self._running = False
        self.loop.call_soon_threadsafe(self.loop.stop)
    
    def Test(
            self,
            url: str,
            num: int,
            callback: Optional[Callable[[int, int], None]] = None
            ) -> Future[timedelta]:
        """Initiates a new HTTP stress test by sending GET request to the
        'url' by the number of 'num'. The optional parameter of callback
        informs the progress of the test. It returns a concurrent.futures.
        Fututre object which can be used to obtain the duration of the 
        operation, cancel it, and accessing other Future APIs.

        Raises asyncio.InvalidStateError if there is an ongoing stress test.
        """
        if asyncio.all_tasks(self.loop):
            raise asyncio.InvalidStateError()

        return asyncio.run_coroutine_threadsafe(
            self._Test(
                url,
                num,
                callback),
            self.loop)
    
    async def _Test(
            self,
            url: str,
            num: int,
            callback: Optional[Callable[[int, int], None]] = None
            ) -> Future[timedelta]:
        global progInfo
        global progInfoLock

        # Initializing the start of the operation...
        try:
            nFinished = 0
            if callback:
                callback(nFinished, num)
            
            startTime = perf_counter()
            async with aiohttp.ClientSession() as session:
                reqs = [
                    asyncio.create_task(
                        session.get(url))
                    for _ in range(num)]
                for future in asyncio.as_completed(reqs):
                    try:
                        await future
                    except Exception:
                        pass
                    nFinished += 1
                    if callback:
                        callback(nFinished, num)
            finishedTime = perf_counter()

            return timedelta(seconds=(finishedTime - startTime))
        except asyncio.CancelledError:
            # Cancelling the issued get requests...
            for task in asyncio.all_tasks():
                task.cancel()
            # Re-throwing the CancelledError...
            raise
    
    def Cancel(self) -> None:
        """Cancels the ongoing test. It does nothing if there is not any."""
        asyncio.run_coroutine_threadsafe(
            self._Cancel(),
            self.loop)
    
    async def _Cancel(self) -> None:
        allTasks = asyncio.all_tasks()
        for task in allTasks:
            task.cancel()


class HttpStressTestWin(tk.Tk):
    def __init__(
            self,
            screenName: str | None = None,
            baseName: str | None = None,
            className: str = 'Tk',
            useTk: bool = True,
            sync: bool = False,
            use: str | None = None
            ) -> None:
        super().__init__(screenName, baseName, className, useTk, sync, use)

        self.title('HTTP stress test')
        self.geometry('650x160+200+200')
        self.resizable(True, False)

        self._TIME_INTRVL = 40
        self._queue = Queue()
        self._showProgID: int
        self._updateElapsedID: int

        self._InitializeGui()

        self.bind('<Return>', self._OnReturn)
    
    def _InitializeGui(self) -> None:
        #
        self.frm_container = tk.Frame(
            master=self)
        self.frm_container.columnconfigure(
            index=1,
            weight=1)
        self.frm_container.pack(
            fill=tk.BOTH,
            expand=1,
            padx=4,
            pady=4)
        
        #
        self.lbl_url = ttk.Label(
            master=self.frm_container,
            text='URL:')
        self.lbl_url.grid(
            column=0,
            row=0,
            sticky=tk.E,
            padx=2,
            pady=2)
        
        #
        self.entry_url = ttk.Entry(
            master=self.frm_container)
        self.entry_url.grid(
            column=1,
            row=0,
            sticky=tk.EW,
            padx=2,
            pady=2)
        
        #
        self.lbl_number = ttk.Label(
            master=self.frm_container,
            text='Number:')
        self.lbl_number.grid(
            column=0,
            row=1,
            sticky=tk.E,
            padx=2,
            pady=2)
        
        #
        self.spn_number = ttk.Spinbox(
            master=self.frm_container,
            values=(5, 10, 20, 50, 100, 200, 500, 1_000, 2_000),
            increment=1)
        self.spn_number.grid(
            column=1,
            row=1,
            sticky=tk.W,
            padx=2,
            pady=2)
        
        #
        self.btn_startStop = ttk.Button(
            master=self.frm_container,
            text='Start',
            command=self._StartStopTest)
        self.btn_startStop.grid(
            column=1,
            row=2,
            sticky=tk.E,
            padx=2,
            pady=2)
        
        #
        self.lblfrm_status = tk.LabelFrame(
            master=self.frm_container,
            text='Status')
        self.lblfrm_status.columnconfigure(
            index=0,
            weight=1)
        self.lblfrm_status.grid(
            column=0,
            columnspan=2,
            row=3,
            sticky=tk.NSEW,
            padx=2,
            pady=2)
        
        #
        self.lbl_status = ttk.Label(
            master=self.lblfrm_status,
            text='Ready')
        self.lbl_status.grid(
            column=0,
            row=0,
            sticky=tk.EW,
            padx=2,
            pady=2)
        
        #
        self.prgrs_status = ttk.Progressbar(
            master=self.lblfrm_status,
            orient=tk.HORIZONTAL,
            mode='determinate')
        self.prgrs_status.grid(
            column=0,
            row=1,
            sticky=tk.EW,
            padx=2,
            pady=2)
    
    def _OnReturn(self, event: tk.Event) -> None:
        self._StartStopTest()
    
    def _StartStopTest(self) -> None:
        global HttpstressTest

        if self.btn_startStop['text'] == 'Start':
            nReqs = int(self.spn_number.get())
            self.prgrs_status.config(maximum=nReqs)
            self.btn_startStop.config(text='Stop')
            self.lbl_status.config(text='Starting test...')

            self._stressTest = HttpstressTest.Test(
                self.entry_url.get(),
                nReqs,
                self.ReportProg)
            self._showProgID = self.after(
                self._TIME_INTRVL,
                self._ShowProg)
            self._updateElapsedID = self.after(
                1000,
                self._UpdateElapsed,
                1)
        elif self.btn_startStop['text'] == 'Stop':
            HttpstressTest.Cancel()
            self.after(
                self._TIME_INTRVL,
                self._CheckCanceling)
        else:
            logging.warning('Button text is incorrect')
    
    def ReportProg(
            self,
            nFinished: int,
            num: int
            ) -> None:
        self._queue.put(ProgInfo(nFinished, num))
    
    def _ShowProg(self) -> None:
        global progInfo
        global progInfoLock

        try:
            currProg = None
            while True:
                currProg = self._queue.get(timeout=0.01)
        except Empty:
            pass
        if currProg is None:
            # Waiting & scheduling for progress info...
            self._showProgID = self.after(
                self._TIME_INTRVL,
                self._ShowProg)
        elif currProg.nFinished < currProg.total:
            self.prgrs_status['value'] = currProg.nFinished
            self._showProgID = self.after(
                self._TIME_INTRVL,
                self._ShowProg)
        else:
            self._ResetStatus()
            self.lbl_status['text'] = str(self._stressTest.result())
            # Canceling the elapsed 'after' callbacks...
            self.after_cancel(self._updateElapsedID)
    
    def _ResetStatus(self) -> None:
        self.btn_startStop.config(text='Start')
        self.lbl_status.config(text='Ready')
        self.prgrs_status.config(value=0)
    
    def _CheckCanceling(self) -> None:
        if self._stressTest.cancelled():
            if self._showProgID:
                self.after_cancel(self._showProgID)
            if self._updateElapsedID:
                self.after_cancel(self._updateElapsedID)
            self._ResetStatus()
        else:
            self.after(
                self._TIME_INTRVL,
                self._CheckCanceling)
    
    def _UpdateElapsed(self, elapsed: int) -> None:
        self.lbl_status['text'] = f'Elapsed {elapsed} seconds'
        self._updateElapsedID = self.after(
                1000,
                self._UpdateElapsed,
                elapsed + 1)


if __name__ == '__main__':
    # Creating the AsyncIO in a thread...
    HttpstressTest = HttpStressTest(name='HttpStressTest')
    HttpstressTest.start()

    # Creating the GUI in the main thread..
    httpStressTestWin = HttpStressTestWin()
    httpStressTestWin.mainloop()

    HttpstressTest.close()
