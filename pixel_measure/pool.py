import os
from queue import Empty, Queue
from threading import Thread


class WorkerThreadPool:
    """Thread pool of Threads used to perform I/O operations
    in parallel.
    """

    def __init__(self, worker_count=None, aggregation_function=None):
        """Initialisation.

        Set up the pool and start all workers.

        Parameters
        ----------
        worker_count : int, optional
            Number of worker threads to use, defaults to os.cpu_count
        """
        self.worker_count = worker_count or os.cpu_count()

        self.workers = []
        self.input_queue = Queue(maxsize=100)
        self.result_queue = Queue()

        for i in range(self.worker_count):
            self.workers.append(WorkerThread(self.input_queue, self.result_queue, aggregation_function))

        self._start()

    def _start(self):
        """Start all worker threads. """
        for w in self.workers:
            w.start()

    def stop(self):
        """Stop all worker threads. """
        for w in self.workers:
            w.stop()

    def execute(self, fn, args):
        """Execute the given function with its arguments in a worker thread.

        This will add the job to the queue and will not wait for the result.
        Use join() to retrieve the result.

        Parameters
        ----------
        fn : function
            Function to execute. It should take all arguments from args, and
            after that a single argument with the requests Session.
        args : tuple
            Arguments that will be passed to the function.
        """
        r = WorkerResult()
        self.input_queue.put((fn, args, r))

    def join(self):
        """Wait for all the jobs to be executed and return the results of all
        jobs in a list.

        Yields
        ------
        WorkerResult
            Results of the executed functions in the order they were
            submitted.
        """
        self.input_queue.join()
        self.stop()

        while not self.result_queue.empty():
            yield self.result_queue.get()


class WorkerResult:
    """Class for storing the result of a job execution in the result queue.

    This allows putting a result instance in the queue on job submission and
    fill in the result later when the job completes. This ensures the result
    output is in the same order as the jobs were submitted.
    """

    def __init__(self):
        """Initialisation. """
        self.result = None
        self.error = None

    def set_result(self, value):
        """Set the result of this job.

        Parameters
        ----------
        value : any
            The result of the execution of the job.
        """
        self.result = value

    def get_result(self):
        """Retrieve the result of this job.

        Returns
        -------
        any
            The result of the execution of the job.
        """
        return self.result

    def set_error(self, error):
        """Set the error, in case the jobs fails with an exception.

        Parameters
        ----------
        error : Exception
            The exception raised while executing this job.
        """
        self.error = error

    def get_error(self):
        """Retrieve the error, if any, of this job.

        Returns
        -------
        Exception
            The exception raised while executing this job.
        """
        return self.error


class WorkerThread(Thread):
    """Worker thread using a local Session to execute functions. """

    def __init__(self, input_queue, result_queue, aggregation_function):
        """Initialisation.

        Bind to the input queue and create a Session.

        Parameters
        ----------
        input_queue : queue.Queue
            Queue to poll for input, this should be in the form of a tuple with
            3 items: function to call, list with arguments and WorkerResult
            instance to store the output. The list with arguments will be
            automatically extended with the local Session instance.
        """
        super().__init__()
        self.input_queue = input_queue
        self.result_queue = result_queue

        self.aggregation_function = aggregation_function
        if self.aggregation_function:
            self.temp_result_queue = Queue()

        self.stopping = False

    def stop(self):
        """Stop the worker thread at the next occasion. This can take up to
        500 ms. """
        self.stopping = True

        if self.aggregation_function:
            aggregate = None

            while not self.temp_result_queue.empty():
                res = self.temp_result_queue.get()

                if res.get_result():
                    aggregate = self.aggregation_function(aggregate, res.get_result())

            thread_result = WorkerResult()
            thread_result.set_result(aggregate)
            self.result_queue.put(thread_result)

    def run(self):
        """Executed while the thread is running. This is called implicitly
        when starting the thread. """
        while not self.stopping:
            try:
                fn, args, r = self.input_queue.get(timeout=0.5)
                args = list(args)

                try:
                    result = fn(*args)
                except BaseException as e:
                    r.set_error(e)
                else:
                    r.set_result(result)
                finally:
                    self.input_queue.task_done()

                    if self.aggregation_function:
                        self.temp_result_queue.put(r)
                    else:
                        self.result_queue.put(r)
            except Empty:
                pass
