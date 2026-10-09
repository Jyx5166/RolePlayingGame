(function() {
	//#region node_modules/@tanstack/query-core/build/modern/subscribable.js
	var Subscribable = class {
		constructor() {
			this.listeners = /* @__PURE__ */ new Set();
			this.subscribe = this.subscribe.bind(this);
		}
		subscribe(listener) {
			this.listeners.add(listener);
			this.onSubscribe();
			return () => {
				this.listeners.delete(listener);
				this.onUnsubscribe();
			};
		}
		hasListeners() {
			return this.listeners.size > 0;
		}
		onSubscribe() {}
		onUnsubscribe() {}
	};
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/focusManager.js
	var FocusManager = class extends Subscribable {
		#focused;
		#cleanup;
		#setup;
		constructor() {
			super();
			this.#setup = (onFocus) => {
				if (typeof window !== "undefined" && window.addEventListener) {
					const listener = () => onFocus();
					window.addEventListener("visibilitychange", listener, false);
					return () => {
						window.removeEventListener("visibilitychange", listener);
					};
				}
			};
		}
		onSubscribe() {
			if (!this.#cleanup) this.setEventListener(this.#setup);
		}
		onUnsubscribe() {
			if (!this.hasListeners()) {
				this.#cleanup?.();
				this.#cleanup = void 0;
			}
		}
		setEventListener(setup) {
			this.#setup = setup;
			this.#cleanup?.();
			this.#cleanup = setup((focused) => {
				if (typeof focused === "boolean") this.setFocused(focused);
				else this.onFocus();
			});
		}
		setFocused(focused) {
			if (this.#focused !== focused) {
				this.#focused = focused;
				this.onFocus();
			}
		}
		onFocus() {
			const isFocused = this.isFocused();
			this.listeners.forEach((listener) => {
				listener(isFocused);
			});
		}
		isFocused() {
			if (typeof this.#focused === "boolean") return this.#focused;
			return globalThis.document?.visibilityState !== "hidden";
		}
	};
	var focusManager = new FocusManager();
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/timeoutManager.js
	var defaultTimeoutProvider = {
		setTimeout: (callback, delay) => setTimeout(callback, delay),
		clearTimeout: (timeoutId) => clearTimeout(timeoutId),
		setInterval: (callback, delay) => setInterval(callback, delay),
		clearInterval: (intervalId) => clearInterval(intervalId)
	};
	var TimeoutManager = class {
		#provider = defaultTimeoutProvider;
		#providerCalled = false;
		setTimeoutProvider(provider) {
			this.#provider = provider;
		}
		setTimeout(callback, delay) {
			return this.#provider.setTimeout(callback, delay);
		}
		clearTimeout(timeoutId) {
			this.#provider.clearTimeout(timeoutId);
		}
		setInterval(callback, delay) {
			return this.#provider.setInterval(callback, delay);
		}
		clearInterval(intervalId) {
			this.#provider.clearInterval(intervalId);
		}
	};
	var timeoutManager = new TimeoutManager();
	function systemSetTimeoutZero(callback) {
		setTimeout(callback, 0);
	}
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/utils.js
	var isServer = typeof window === "undefined" || "Deno" in globalThis;
	function noop$2() {}
	function functionalUpdate(updater, input) {
		return typeof updater === "function" ? updater(input) : updater;
	}
	function isValidTimeout(value) {
		return typeof value === "number" && value >= 0 && value !== Infinity;
	}
	function timeUntilStale(updatedAt, staleTime) {
		return Math.max(updatedAt + (staleTime || 0) - Date.now(), 0);
	}
	function resolveStaleTime(staleTime, query) {
		return typeof staleTime === "function" ? staleTime(query) : staleTime;
	}
	function resolveQueryBoolean(option, query) {
		return typeof option === "function" ? option(query) : option;
	}
	function matchQuery(filters, query) {
		const { type = "all", exact, fetchStatus, predicate, queryKey, stale } = filters;
		if (queryKey) {
			if (exact) {
				if (query.queryHash !== hashQueryKeyByOptions(queryKey, query.options)) return false;
			} else if (!partialMatchKey(query.queryKey, queryKey)) return false;
		}
		if (type !== "all") {
			const isActive = query.isActive();
			if (type === "active" && !isActive) return false;
			if (type === "inactive" && isActive) return false;
		}
		if (typeof stale === "boolean" && query.isStale() !== stale) return false;
		if (fetchStatus && fetchStatus !== query.state.fetchStatus) return false;
		if (predicate && !predicate(query)) return false;
		return true;
	}
	function matchMutation(filters, mutation) {
		const { exact, status, predicate, mutationKey } = filters;
		if (mutationKey) {
			if (!mutation.options.mutationKey) return false;
			if (exact) {
				if (hashKey(mutation.options.mutationKey) !== hashKey(mutationKey)) return false;
			} else if (!partialMatchKey(mutation.options.mutationKey, mutationKey)) return false;
		}
		if (status && mutation.state.status !== status) return false;
		if (predicate && !predicate(mutation)) return false;
		return true;
	}
	function hashQueryKeyByOptions(queryKey, options) {
		return (options?.queryKeyHashFn || hashKey)(queryKey);
	}
	function hashKey(queryKey) {
		return JSON.stringify(queryKey, (_, val) => isPlainObject$3(val) ? Object.keys(val).sort().reduce((result, key) => {
			result[key] = val[key];
			return result;
		}, {}) : val);
	}
	function partialMatchKey(a, b) {
		if (a === b) return true;
		if (typeof a !== typeof b) return false;
		if (a && b && typeof a === "object" && typeof b === "object") {
			if (Array.isArray(a) && Array.isArray(b)) {
				for (let i = 0; i < b.length; i++) if (!partialMatchKey(a[i], b[i])) return false;
				return true;
			}
			const bKeys = Object.keys(b);
			for (const key of bKeys) if (!partialMatchKey(a[key], b[key])) return false;
			return true;
		}
		return false;
	}
	var hasOwn$1 = Object.prototype.hasOwnProperty;
	function replaceEqualDeep(a, b, depth = 0) {
		if (a === b) return a;
		if (depth > 500) return b;
		const array = isPlainArray(a) && isPlainArray(b);
		if (!array && !(isPlainObject$3(a) && isPlainObject$3(b))) return b;
		const aSize = (array ? a : Object.keys(a)).length;
		const bItems = array ? b : Object.keys(b);
		const bSize = bItems.length;
		const copy = array ? new Array(bSize) : {};
		let equalItems = 0;
		for (let i = 0; i < bSize; i++) {
			const key = array ? i : bItems[i];
			const aItem = a[key];
			const bItem = b[key];
			if (aItem === bItem) {
				copy[key] = aItem;
				if (array ? i < aSize : hasOwn$1.call(a, key)) equalItems++;
				continue;
			}
			if (aItem === null || bItem === null || typeof aItem !== "object" || typeof bItem !== "object") {
				copy[key] = bItem;
				continue;
			}
			const v = replaceEqualDeep(aItem, bItem, depth + 1);
			copy[key] = v;
			if (v === aItem) equalItems++;
		}
		return aSize === bSize && equalItems === aSize ? a : copy;
	}
	function shallowEqualObjects(a, b) {
		if (!b || Object.keys(a).length !== Object.keys(b).length) return false;
		for (const key in a) if (a[key] !== b[key]) return false;
		return true;
	}
	function isPlainArray(value) {
		return Array.isArray(value) && value.length === Object.keys(value).length;
	}
	function isPlainObject$3(o) {
		if (!hasObjectPrototype(o)) return false;
		const ctor = o.constructor;
		if (ctor === void 0) return true;
		const prot = ctor.prototype;
		if (!hasObjectPrototype(prot)) return false;
		if (!prot.hasOwnProperty("isPrototypeOf")) return false;
		if (Object.getPrototypeOf(o) !== Object.prototype) return false;
		return true;
	}
	function hasObjectPrototype(o) {
		return Object.prototype.toString.call(o) === "[object Object]";
	}
	function sleep(timeout) {
		return new Promise((resolve) => {
			timeoutManager.setTimeout(resolve, timeout);
		});
	}
	function replaceData(prevData, data, options) {
		if (typeof options.structuralSharing === "function") return options.structuralSharing(prevData, data);
		else if (options.structuralSharing !== false) return replaceEqualDeep(prevData, data);
		return data;
	}
	function addToEnd(items, item, max = 0) {
		const newItems = [...items, item];
		return max && newItems.length > max ? newItems.slice(1) : newItems;
	}
	function addToStart(items, item, max = 0) {
		const newItems = [item, ...items];
		return max && newItems.length > max ? newItems.slice(0, -1) : newItems;
	}
	var skipToken = /* @__PURE__ */ Symbol();
	function ensureQueryFn(options, fetchOptions) {
		if (!options.queryFn && fetchOptions?.initialPromise) return () => fetchOptions.initialPromise;
		if (!options.queryFn || options.queryFn === skipToken) return () => Promise.reject(/* @__PURE__ */ new Error(`Missing queryFn: '${options.queryHash}'`));
		return options.queryFn;
	}
	function shouldThrowError(throwOnError, params) {
		if (typeof throwOnError === "function") return throwOnError(...params);
		return !!throwOnError;
	}
	function addConsumeAwareSignal(object, getSignal, onCancelled) {
		let consumed = false;
		let signal;
		Object.defineProperty(object, "signal", {
			enumerable: true,
			get: () => {
				signal ??= getSignal();
				if (consumed) return signal;
				consumed = true;
				if (signal.aborted) onCancelled();
				else signal.addEventListener("abort", onCancelled, { once: true });
				return signal;
			}
		});
		return object;
	}
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/environmentManager.js
	var environmentManager = /* @__PURE__ */ (() => {
		let isServerFn = () => isServer;
		return {
			/**
			* Returns whether the current runtime should be treated as a server environment.
			*/
			isServer() {
				return isServerFn();
			},
			/**
			* Overrides the server check globally.
			*/
			setIsServer(isServerValue) {
				isServerFn = isServerValue;
			}
		};
	})();
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/thenable.js
	function pendingThenable() {
		let resolve;
		let reject;
		const thenable = new Promise((_resolve, _reject) => {
			resolve = _resolve;
			reject = _reject;
		});
		thenable.status = "pending";
		thenable.catch(() => {});
		function finalize(data) {
			Object.assign(thenable, data);
			delete thenable.resolve;
			delete thenable.reject;
		}
		thenable.resolve = (value) => {
			finalize({
				status: "fulfilled",
				value
			});
			resolve(value);
		};
		thenable.reject = (reason) => {
			finalize({
				status: "rejected",
				reason
			});
			reject(reason);
		};
		return thenable;
	}
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/notifyManager.js
	var defaultScheduler = systemSetTimeoutZero;
	function createNotifyManager() {
		let queue = [];
		let transactions = 0;
		let notifyFn = (callback) => {
			callback();
		};
		let batchNotifyFn = (callback) => {
			callback();
		};
		let scheduleFn = defaultScheduler;
		const schedule = (callback) => {
			if (transactions) queue.push(callback);
			else scheduleFn(() => {
				notifyFn(callback);
			});
		};
		const flush = () => {
			const originalQueue = queue;
			queue = [];
			if (originalQueue.length) scheduleFn(() => {
				batchNotifyFn(() => {
					originalQueue.forEach((callback) => {
						notifyFn(callback);
					});
				});
			});
		};
		return {
			batch: (callback) => {
				let result;
				transactions++;
				try {
					result = callback();
				} finally {
					transactions--;
					if (!transactions) flush();
				}
				return result;
			},
			/**
			* All calls to the wrapped function will be batched.
			*/
			batchCalls: (callback) => {
				return (...args) => {
					schedule(() => {
						callback(...args);
					});
				};
			},
			schedule,
			/**
			* Use this method to set a custom notify function.
			* This can be used to for example wrap notifications with `React.act` while running tests.
			*/
			setNotifyFunction: (fn) => {
				notifyFn = fn;
			},
			/**
			* Use this method to set a custom function to batch notifications together into a single tick.
			* By default React Query will use the batch function provided by ReactDOM or React Native.
			*/
			setBatchNotifyFunction: (fn) => {
				batchNotifyFn = fn;
			},
			setScheduler: (fn) => {
				scheduleFn = fn;
			}
		};
	}
	var notifyManager = createNotifyManager();
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/onlineManager.js
	var OnlineManager = class extends Subscribable {
		#online = true;
		#cleanup;
		#setup;
		constructor() {
			super();
			this.#setup = (onOnline) => {
				if (typeof window !== "undefined" && window.addEventListener) {
					const onlineListener = () => onOnline(true);
					const offlineListener = () => onOnline(false);
					window.addEventListener("online", onlineListener, false);
					window.addEventListener("offline", offlineListener, false);
					return () => {
						window.removeEventListener("online", onlineListener);
						window.removeEventListener("offline", offlineListener);
					};
				}
			};
		}
		onSubscribe() {
			if (!this.#cleanup) this.setEventListener(this.#setup);
		}
		onUnsubscribe() {
			if (!this.hasListeners()) {
				this.#cleanup?.();
				this.#cleanup = void 0;
			}
		}
		setEventListener(setup) {
			this.#setup = setup;
			this.#cleanup?.();
			this.#cleanup = setup(this.setOnline.bind(this));
		}
		setOnline(online) {
			if (this.#online !== online) {
				this.#online = online;
				this.listeners.forEach((listener) => {
					listener(online);
				});
			}
		}
		isOnline() {
			return this.#online;
		}
	};
	var onlineManager = new OnlineManager();
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/retryer.js
	function defaultRetryDelay(failureCount) {
		return Math.min(1e3 * 2 ** failureCount, 3e4);
	}
	function canFetch(networkMode) {
		return (networkMode ?? "online") === "online" ? onlineManager.isOnline() : true;
	}
	var CancelledError = class extends Error {
		constructor(options) {
			super("CancelledError");
			this.revert = options?.revert;
			this.silent = options?.silent;
		}
	};
	function createRetryer(config) {
		let isRetryCancelled = false;
		let failureCount = 0;
		let continueFn;
		const thenable = pendingThenable();
		const isResolved = () => thenable.status !== "pending";
		const cancel = (cancelOptions) => {
			if (!isResolved()) {
				const error = new CancelledError(cancelOptions);
				reject(error);
				config.onCancel?.(error);
			}
		};
		const cancelRetry = () => {
			isRetryCancelled = true;
		};
		const continueRetry = () => {
			isRetryCancelled = false;
		};
		const canContinue = () => focusManager.isFocused() && (config.networkMode === "always" || onlineManager.isOnline()) && config.canRun();
		const canStart = () => canFetch(config.networkMode) && config.canRun();
		const resolve = (value) => {
			if (!isResolved()) {
				continueFn?.();
				thenable.resolve(value);
			}
		};
		const reject = (value) => {
			if (!isResolved()) {
				continueFn?.();
				thenable.reject(value);
			}
		};
		const pause = () => {
			return new Promise((continueResolve) => {
				continueFn = (value) => {
					if (isResolved() || canContinue()) continueResolve(value);
				};
				config.onPause?.();
			}).then(() => {
				continueFn = void 0;
				if (!isResolved()) config.onContinue?.();
			});
		};
		const run = () => {
			if (isResolved()) return;
			let promiseOrValue;
			const initialPromise = failureCount === 0 ? config.initialPromise : void 0;
			try {
				promiseOrValue = initialPromise ?? config.fn();
			} catch (error) {
				promiseOrValue = Promise.reject(error);
			}
			Promise.resolve(promiseOrValue).then(resolve).catch((error) => {
				if (isResolved()) return;
				const retry = config.retry ?? (environmentManager.isServer() ? 0 : 3);
				const retryDelay = config.retryDelay ?? defaultRetryDelay;
				const delay = typeof retryDelay === "function" ? retryDelay(failureCount, error) : retryDelay;
				const shouldRetry = retry === true || typeof retry === "number" && failureCount < retry || typeof retry === "function" && retry(failureCount, error);
				if (isRetryCancelled || !shouldRetry) {
					reject(error);
					return;
				}
				failureCount++;
				config.onFail?.(failureCount, error);
				sleep(delay).then(() => {
					return canContinue() ? void 0 : pause();
				}).then(() => {
					if (isRetryCancelled) reject(error);
					else run();
				});
			});
		};
		return {
			promise: thenable,
			status: () => thenable.status,
			cancel,
			continue: () => {
				continueFn?.();
				return thenable;
			},
			cancelRetry,
			continueRetry,
			canStart,
			start: () => {
				if (canStart()) run();
				else pause().then(run);
				return thenable;
			}
		};
	}
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/removable.js
	var Removable = class {
		#gcTimeout;
		destroy() {
			this.clearGcTimeout();
		}
		scheduleGc() {
			this.clearGcTimeout();
			if (isValidTimeout(this.gcTime)) this.#gcTimeout = timeoutManager.setTimeout(() => {
				this.optionalRemove();
			}, this.gcTime);
		}
		updateGcTime(newGcTime) {
			this.gcTime = Math.max(this.gcTime || 0, newGcTime ?? (environmentManager.isServer() ? Infinity : 3e5));
		}
		clearGcTimeout() {
			if (this.#gcTimeout !== void 0) {
				timeoutManager.clearTimeout(this.#gcTimeout);
				this.#gcTimeout = void 0;
			}
		}
	};
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/infiniteQueryBehavior.js
	function infiniteQueryBehavior(pages) {
		return { onFetch: (context, query) => {
			const options = context.options;
			const direction = context.fetchOptions?.meta?.fetchMore?.direction;
			const oldPages = context.state.data?.pages || [];
			const oldPageParams = context.state.data?.pageParams || [];
			let result = {
				pages: [],
				pageParams: []
			};
			let currentPage = 0;
			const fetchFn = async () => {
				let cancelled = false;
				const addSignalProperty = (object) => {
					addConsumeAwareSignal(object, () => context.signal, () => cancelled = true);
				};
				const queryFn = ensureQueryFn(context.options, context.fetchOptions);
				const fetchPage = async (data, param, previous) => {
					if (cancelled) return Promise.reject(context.signal.reason);
					if (param == null && data.pages.length) return Promise.resolve(data);
					const createQueryFnContext = () => {
						const queryFnContext2 = {
							client: context.client,
							queryKey: context.queryKey,
							pageParam: param,
							direction: previous ? "backward" : "forward",
							meta: context.options.meta
						};
						addSignalProperty(queryFnContext2);
						return queryFnContext2;
					};
					const queryFnContext = createQueryFnContext();
					const page = await queryFn(queryFnContext);
					const { maxPages } = context.options;
					const addTo = previous ? addToStart : addToEnd;
					return {
						pages: addTo(data.pages, page, maxPages),
						pageParams: addTo(data.pageParams, param, maxPages)
					};
				};
				if (direction && oldPages.length) {
					const previous = direction === "backward";
					const pageParamFn = previous ? getPreviousPageParam : getNextPageParam;
					const oldData = {
						pages: oldPages,
						pageParams: oldPageParams
					};
					result = await fetchPage(oldData, pageParamFn(options, oldData), previous);
				} else {
					const remainingPages = pages ?? oldPages.length;
					do {
						const param = currentPage === 0 ? oldPageParams[0] ?? options.initialPageParam : getNextPageParam(options, result);
						if (currentPage > 0 && param == null) break;
						result = await fetchPage(result, param);
						currentPage++;
					} while (currentPage < remainingPages);
				}
				return result;
			};
			if (context.options.persister) context.fetchFn = () => {
				return context.options.persister?.(fetchFn, {
					client: context.client,
					queryKey: context.queryKey,
					meta: context.options.meta,
					signal: context.signal
				}, query);
			};
			else context.fetchFn = fetchFn;
		} };
	}
	function getNextPageParam(options, { pages, pageParams }) {
		const lastIndex = pages.length - 1;
		return pages.length > 0 ? options.getNextPageParam(pages[lastIndex], pages, pageParams[lastIndex], pageParams) : void 0;
	}
	function getPreviousPageParam(options, { pages, pageParams }) {
		return pages.length > 0 ? options.getPreviousPageParam?.(pages[0], pages, pageParams[0], pageParams) : void 0;
	}
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/query.js
	var Query = class extends Removable {
		#queryType;
		#initialState;
		#revertState;
		#cache;
		#client;
		#retryer;
		#defaultOptions;
		#abortSignalConsumed;
		constructor(config) {
			super();
			this.#abortSignalConsumed = false;
			this.#defaultOptions = config.defaultOptions;
			this.setOptions(config.options);
			this.observers = [];
			this.#client = config.client;
			this.#cache = this.#client.getQueryCache();
			this.queryKey = config.queryKey;
			this.queryHash = config.queryHash;
			this.#initialState = getDefaultState$1(this.options);
			this.state = config.state ?? this.#initialState;
			this.scheduleGc();
		}
		get meta() {
			return this.options.meta;
		}
		get queryType() {
			return this.#queryType;
		}
		get promise() {
			return this.#retryer?.promise;
		}
		setOptions(options) {
			this.options = {
				...this.#defaultOptions,
				...options
			};
			if (options?._type) this.#queryType = options._type;
			this.updateGcTime(this.options.gcTime);
			if (this.state && this.state.data === void 0) {
				const defaultState = getDefaultState$1(this.options);
				if (defaultState.data !== void 0) {
					this.setState(successState(defaultState.data, defaultState.dataUpdatedAt));
					this.#initialState = defaultState;
				}
			}
		}
		optionalRemove() {
			if (!this.observers.length && this.state.fetchStatus === "idle") this.#cache.remove(this);
		}
		setData(newData, options) {
			const data = replaceData(this.state.data, newData, this.options);
			this.#dispatch({
				data,
				type: "success",
				dataUpdatedAt: options?.updatedAt,
				manual: options?.manual
			});
			return data;
		}
		setState(state) {
			this.#dispatch({
				type: "setState",
				state
			});
		}
		cancel(options) {
			const promise = this.#retryer?.promise;
			this.#retryer?.cancel(options);
			return promise ? promise.then(noop$2).catch(noop$2) : Promise.resolve();
		}
		destroy() {
			super.destroy();
			this.cancel({ silent: true });
		}
		get resetState() {
			return this.#initialState;
		}
		reset() {
			this.destroy();
			this.setState(this.resetState);
		}
		isActive() {
			return this.observers.some((observer) => resolveQueryBoolean(observer.options.enabled, this) !== false);
		}
		isDisabled() {
			if (this.getObserversCount() > 0) return !this.isActive();
			return this.options.queryFn === skipToken || !this.isFetched();
		}
		isFetched() {
			return this.state.dataUpdateCount + this.state.errorUpdateCount > 0;
		}
		isStatic() {
			if (this.getObserversCount() > 0) return this.observers.some((observer) => resolveStaleTime(observer.options.staleTime, this) === "static");
			return false;
		}
		isStale() {
			if (this.getObserversCount() > 0) return this.observers.some((observer) => observer.getCurrentResult().isStale);
			return this.state.data === void 0 || this.state.isInvalidated;
		}
		isStaleByTime(staleTime = 0) {
			if (this.state.data === void 0) return true;
			if (staleTime === "static") return false;
			if (this.state.isInvalidated) return true;
			return !timeUntilStale(this.state.dataUpdatedAt, staleTime);
		}
		onFocus() {
			this.observers.find((x) => x.shouldFetchOnWindowFocus())?.refetch({ cancelRefetch: false });
			this.#retryer?.continue();
		}
		onOnline() {
			this.observers.find((x) => x.shouldFetchOnReconnect())?.refetch({ cancelRefetch: false });
			this.#retryer?.continue();
		}
		addObserver(observer) {
			if (!this.observers.includes(observer)) {
				this.observers.push(observer);
				this.clearGcTimeout();
				this.#cache.notify({
					type: "observerAdded",
					query: this,
					observer
				});
			}
		}
		removeObserver(observer) {
			if (this.observers.includes(observer)) {
				this.observers = this.observers.filter((x) => x !== observer);
				if (!this.observers.length) {
					if (this.#retryer) {
						if (this.#abortSignalConsumed || this.#isInitialPausedFetch()) this.#retryer.cancel({ revert: true });
						else this.#retryer.cancelRetry();
					}
					this.scheduleGc();
				}
				this.#cache.notify({
					type: "observerRemoved",
					query: this,
					observer
				});
			}
		}
		getObserversCount() {
			return this.observers.length;
		}
		#isInitialPausedFetch() {
			return this.state.fetchStatus === "paused" && this.state.status === "pending";
		}
		invalidate() {
			if (!this.state.isInvalidated) this.#dispatch({ type: "invalidate" });
		}
		async fetch(options, fetchOptions) {
			if (this.state.fetchStatus !== "idle" && this.#retryer?.status() !== "rejected") {
				if (this.state.data !== void 0 && fetchOptions?.cancelRefetch) this.cancel({ silent: true });
				else if (this.#retryer) {
					this.#retryer.continueRetry();
					return this.#retryer.promise;
				}
			}
			if (options) this.setOptions(options);
			if (!this.options.queryFn) {
				const observer = this.observers.find((x) => x.options.queryFn);
				if (observer) this.setOptions(observer.options);
			}
			const abortController = new AbortController();
			const addSignalProperty = (object) => {
				Object.defineProperty(object, "signal", {
					enumerable: true,
					get: () => {
						this.#abortSignalConsumed = true;
						return abortController.signal;
					}
				});
			};
			const fetchFn = () => {
				const queryFn = ensureQueryFn(this.options, fetchOptions);
				const createQueryFnContext = () => {
					const queryFnContext2 = {
						client: this.#client,
						queryKey: this.queryKey,
						meta: this.meta
					};
					addSignalProperty(queryFnContext2);
					return queryFnContext2;
				};
				const queryFnContext = createQueryFnContext();
				this.#abortSignalConsumed = false;
				if (this.options.persister) return this.options.persister(queryFn, queryFnContext, this);
				return queryFn(queryFnContext);
			};
			const createFetchContext = () => {
				const context2 = {
					fetchOptions,
					options: this.options,
					queryKey: this.queryKey,
					client: this.#client,
					state: this.state,
					fetchFn
				};
				addSignalProperty(context2);
				return context2;
			};
			const context = createFetchContext();
			(this.#queryType === "infinite" ? infiniteQueryBehavior(this.options.pages) : this.options.behavior)?.onFetch(context, this);
			this.#revertState = this.state;
			if (this.state.fetchStatus === "idle" || this.state.fetchMeta !== context.fetchOptions?.meta) this.#dispatch({
				type: "fetch",
				meta: context.fetchOptions?.meta
			});
			this.#retryer = createRetryer({
				initialPromise: fetchOptions?.initialPromise,
				fn: context.fetchFn,
				onCancel: (error) => {
					if (error instanceof CancelledError && error.revert) this.setState({
						...this.#revertState,
						fetchStatus: "idle"
					});
					abortController.abort();
				},
				onFail: (failureCount, error) => {
					this.#dispatch({
						type: "failed",
						failureCount,
						error
					});
				},
				onPause: () => {
					this.#dispatch({ type: "pause" });
				},
				onContinue: () => {
					this.#dispatch({ type: "continue" });
				},
				retry: context.options.retry,
				retryDelay: context.options.retryDelay,
				networkMode: context.options.networkMode,
				canRun: () => true
			});
			try {
				const data = await this.#retryer.start();
				if (data === void 0) throw new Error(`${this.queryHash} data is undefined`);
				this.setData(data);
				this.#cache.config.onSuccess?.(data, this);
				this.#cache.config.onSettled?.(data, this.state.error, this);
				return data;
			} catch (error) {
				if (error instanceof CancelledError) {
					if (error.silent) return this.#retryer.promise;
					else if (error.revert) {
						if (this.state.data === void 0) throw error;
						return this.state.data;
					}
				}
				this.#dispatch({
					type: "error",
					error
				});
				this.#cache.config.onError?.(error, this);
				this.#cache.config.onSettled?.(this.state.data, error, this);
				throw error;
			} finally {
				this.scheduleGc();
			}
		}
		#dispatch(action) {
			const reducer = (state) => {
				switch (action.type) {
					case "failed": return {
						...state,
						fetchFailureCount: action.failureCount,
						fetchFailureReason: action.error
					};
					case "pause": return {
						...state,
						fetchStatus: "paused"
					};
					case "continue": return {
						...state,
						fetchStatus: "fetching"
					};
					case "fetch": return {
						...state,
						...fetchState(state.data, this.options),
						fetchMeta: action.meta ?? null
					};
					case "success":
						const newState = {
							...state,
							...successState(action.data, action.dataUpdatedAt),
							dataUpdateCount: state.dataUpdateCount + 1,
							...!action.manual && {
								fetchStatus: "idle",
								fetchFailureCount: 0,
								fetchFailureReason: null
							}
						};
						this.#revertState = action.manual ? newState : void 0;
						return newState;
					case "error":
						const error = action.error;
						return {
							...state,
							error,
							errorUpdateCount: state.errorUpdateCount + 1,
							errorUpdatedAt: Date.now(),
							fetchFailureCount: state.fetchFailureCount + 1,
							fetchFailureReason: error,
							fetchStatus: "idle",
							status: "error",
							isInvalidated: true
						};
					case "invalidate": return {
						...state,
						isInvalidated: true
					};
					case "setState": return {
						...state,
						...action.state
					};
				}
			};
			this.state = reducer(this.state);
			notifyManager.batch(() => {
				this.observers.forEach((observer) => {
					observer.onQueryUpdate();
				});
				this.#cache.notify({
					query: this,
					type: "updated",
					action
				});
			});
		}
	};
	function fetchState(data, options) {
		return {
			fetchFailureCount: 0,
			fetchFailureReason: null,
			fetchStatus: canFetch(options.networkMode) ? "fetching" : "paused",
			...data === void 0 && {
				error: null,
				status: "pending"
			}
		};
	}
	function successState(data, dataUpdatedAt) {
		return {
			data,
			dataUpdatedAt: dataUpdatedAt ?? Date.now(),
			error: null,
			isInvalidated: false,
			status: "success"
		};
	}
	function getDefaultState$1(options) {
		const data = typeof options.initialData === "function" ? options.initialData() : options.initialData;
		const hasData = data !== void 0;
		const initialDataUpdatedAt = hasData ? typeof options.initialDataUpdatedAt === "function" ? options.initialDataUpdatedAt() : options.initialDataUpdatedAt : 0;
		return {
			data,
			dataUpdateCount: 0,
			dataUpdatedAt: hasData ? initialDataUpdatedAt ?? Date.now() : 0,
			error: null,
			errorUpdateCount: 0,
			errorUpdatedAt: 0,
			fetchFailureCount: 0,
			fetchFailureReason: null,
			fetchMeta: null,
			isInvalidated: false,
			status: hasData ? "success" : "pending",
			fetchStatus: "idle"
		};
	}
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/queryObserver.js
	var QueryObserver = class extends Subscribable {
		constructor(client, options) {
			super();
			this.options = options;
			this.#client = client;
			this.#selectError = null;
			this.#currentThenable = pendingThenable();
			this.bindMethods();
			this.setOptions(options);
		}
		#client;
		#currentQuery = void 0;
		#currentQueryInitialState = void 0;
		#currentResult = void 0;
		#currentResultState;
		#currentResultOptions;
		#currentThenable;
		#selectError;
		#selectFn;
		#selectResult;
		#lastQueryWithDefinedData;
		#staleTimeoutId;
		#refetchIntervalId;
		#currentRefetchInterval;
		#trackedProps = /* @__PURE__ */ new Set();
		bindMethods() {
			this.refetch = this.refetch.bind(this);
		}
		onSubscribe() {
			if (this.listeners.size === 1) {
				this.#currentQuery.addObserver(this);
				if (shouldFetchOnMount(this.#currentQuery, this.options)) this.#executeFetch();
				else this.updateResult();
				this.#updateTimers();
			}
		}
		onUnsubscribe() {
			if (!this.hasListeners()) this.destroy();
		}
		shouldFetchOnReconnect() {
			return shouldFetchOn(this.#currentQuery, this.options, this.options.refetchOnReconnect);
		}
		shouldFetchOnWindowFocus() {
			return shouldFetchOn(this.#currentQuery, this.options, this.options.refetchOnWindowFocus);
		}
		destroy() {
			this.listeners = /* @__PURE__ */ new Set();
			this.#clearStaleTimeout();
			this.#clearRefetchInterval();
			this.#currentQuery.removeObserver(this);
		}
		setOptions(options) {
			const prevOptions = this.options;
			const prevQuery = this.#currentQuery;
			this.options = this.#client.defaultQueryOptions(options);
			if (this.options.enabled !== void 0 && typeof this.options.enabled !== "boolean" && typeof this.options.enabled !== "function" && typeof resolveQueryBoolean(this.options.enabled, this.#currentQuery) !== "boolean") throw new Error("Expected enabled to be a boolean or a callback that returns a boolean");
			this.#updateQuery();
			this.#currentQuery.setOptions(this.options);
			if (prevOptions._defaulted && !shallowEqualObjects(this.options, prevOptions)) this.#client.getQueryCache().notify({
				type: "observerOptionsUpdated",
				query: this.#currentQuery,
				observer: this
			});
			const mounted = this.hasListeners();
			if (mounted && shouldFetchOptionally(this.#currentQuery, prevQuery, this.options, prevOptions)) this.#executeFetch();
			this.updateResult();
			if (mounted && (this.#currentQuery !== prevQuery || resolveQueryBoolean(this.options.enabled, this.#currentQuery) !== resolveQueryBoolean(prevOptions.enabled, this.#currentQuery) || resolveStaleTime(this.options.staleTime, this.#currentQuery) !== resolveStaleTime(prevOptions.staleTime, this.#currentQuery))) this.#updateStaleTimeout();
			const nextRefetchInterval = this.#computeRefetchInterval();
			if (mounted && (this.#currentQuery !== prevQuery || resolveQueryBoolean(this.options.enabled, this.#currentQuery) !== resolveQueryBoolean(prevOptions.enabled, this.#currentQuery) || nextRefetchInterval !== this.#currentRefetchInterval)) this.#updateRefetchInterval(nextRefetchInterval);
		}
		getOptimisticResult(options) {
			const query = this.#client.getQueryCache().build(this.#client, options);
			const result = this.createResult(query, options);
			if (shouldAssignObserverCurrentProperties(this, result)) {
				this.#currentResult = result;
				this.#currentResultOptions = this.options;
				this.#currentResultState = this.#currentQuery.state;
			}
			return result;
		}
		getCurrentResult() {
			return this.#currentResult;
		}
		trackResult(result, onPropTracked) {
			return new Proxy(result, { get: (target, key) => {
				this.trackProp(key);
				onPropTracked?.(key);
				if (key === "promise") {
					this.trackProp("data");
					if (!this.options.experimental_prefetchInRender && this.#currentThenable.status === "pending") this.#currentThenable.reject(/* @__PURE__ */ new Error("experimental_prefetchInRender feature flag is not enabled"));
				}
				return Reflect.get(target, key);
			} });
		}
		trackProp(key) {
			this.#trackedProps.add(key);
		}
		getCurrentQuery() {
			return this.#currentQuery;
		}
		refetch({ ...options } = {}) {
			return this.fetch({ ...options });
		}
		fetchOptimistic(options) {
			const defaultedOptions = this.#client.defaultQueryOptions(options);
			const query = this.#client.getQueryCache().build(this.#client, defaultedOptions);
			return query.fetch().then(() => this.createResult(query, defaultedOptions));
		}
		fetch(fetchOptions) {
			return this.#executeFetch({
				...fetchOptions,
				cancelRefetch: fetchOptions.cancelRefetch ?? true
			}).then(() => {
				this.updateResult();
				return this.#currentResult;
			});
		}
		#executeFetch(fetchOptions) {
			this.#updateQuery();
			let promise = this.#currentQuery.fetch(this.options, fetchOptions);
			if (!fetchOptions?.throwOnError) promise = promise.catch(noop$2);
			return promise;
		}
		#updateStaleTimeout() {
			this.#clearStaleTimeout();
			const staleTime = resolveStaleTime(this.options.staleTime, this.#currentQuery);
			if (environmentManager.isServer() || this.#currentResult.isStale || !isValidTimeout(staleTime)) return;
			const timeout = timeUntilStale(this.#currentResult.dataUpdatedAt, staleTime) + 1;
			this.#staleTimeoutId = timeoutManager.setTimeout(() => {
				if (!this.#currentResult.isStale) this.updateResult();
			}, timeout);
		}
		#computeRefetchInterval() {
			return (typeof this.options.refetchInterval === "function" ? this.options.refetchInterval(this.#currentQuery) : this.options.refetchInterval) ?? false;
		}
		#updateRefetchInterval(nextInterval) {
			this.#clearRefetchInterval();
			this.#currentRefetchInterval = nextInterval;
			if (environmentManager.isServer() || resolveQueryBoolean(this.options.enabled, this.#currentQuery) === false || !isValidTimeout(this.#currentRefetchInterval) || this.#currentRefetchInterval === 0) return;
			this.#refetchIntervalId = timeoutManager.setInterval(() => {
				if (this.options.refetchIntervalInBackground || focusManager.isFocused()) this.#executeFetch();
			}, this.#currentRefetchInterval);
		}
		#updateTimers() {
			this.#updateStaleTimeout();
			this.#updateRefetchInterval(this.#computeRefetchInterval());
		}
		#clearStaleTimeout() {
			if (this.#staleTimeoutId !== void 0) {
				timeoutManager.clearTimeout(this.#staleTimeoutId);
				this.#staleTimeoutId = void 0;
			}
		}
		#clearRefetchInterval() {
			if (this.#refetchIntervalId !== void 0) {
				timeoutManager.clearInterval(this.#refetchIntervalId);
				this.#refetchIntervalId = void 0;
			}
		}
		createResult(query, options) {
			const prevQuery = this.#currentQuery;
			const prevOptions = this.options;
			const prevResult = this.#currentResult;
			const prevResultState = this.#currentResultState;
			const prevResultOptions = this.#currentResultOptions;
			const queryInitialState = query !== prevQuery ? query.state : this.#currentQueryInitialState;
			const { state } = query;
			let newState = { ...state };
			let isPlaceholderData = false;
			let data;
			if (options._optimisticResults) {
				const mounted = this.hasListeners();
				const fetchOnMount = !mounted && shouldFetchOnMount(query, options);
				const fetchOptionally = mounted && shouldFetchOptionally(query, prevQuery, options, prevOptions);
				if (fetchOnMount || fetchOptionally) newState = {
					...newState,
					...fetchState(state.data, query.options)
				};
				if (options._optimisticResults === "isRestoring") newState.fetchStatus = "idle";
			}
			let { error, errorUpdatedAt, status } = newState;
			data = newState.data;
			let skipSelect = false;
			if (options.placeholderData !== void 0 && data === void 0 && status === "pending") {
				let placeholderData;
				if (prevResult?.isPlaceholderData && options.placeholderData === prevResultOptions?.placeholderData) {
					placeholderData = prevResult.data;
					skipSelect = true;
				} else placeholderData = typeof options.placeholderData === "function" ? options.placeholderData(this.#lastQueryWithDefinedData?.state.data, this.#lastQueryWithDefinedData) : options.placeholderData;
				if (placeholderData !== void 0) {
					status = "success";
					data = replaceData(prevResult?.data, placeholderData, options);
					isPlaceholderData = true;
				}
			}
			if (options.select && data !== void 0 && !skipSelect) {
				if (prevResult && data === prevResultState?.data && options.select === this.#selectFn) data = this.#selectResult;
				else try {
					this.#selectFn = options.select;
					data = options.select(data);
					data = replaceData(prevResult?.data, data, options);
					this.#selectResult = data;
					this.#selectError = null;
				} catch (selectError) {
					this.#selectError = selectError;
				}
			}
			if (this.#selectError) {
				error = this.#selectError;
				data = this.#selectResult;
				errorUpdatedAt = Date.now();
				status = "error";
			}
			const isFetching = newState.fetchStatus === "fetching";
			const isPending = status === "pending";
			const isError = status === "error";
			const isLoading = isPending && isFetching;
			const hasData = data !== void 0;
			const nextResult = {
				status,
				fetchStatus: newState.fetchStatus,
				isPending,
				isSuccess: status === "success",
				isError,
				isInitialLoading: isLoading,
				isLoading,
				data,
				dataUpdatedAt: newState.dataUpdatedAt,
				error,
				errorUpdatedAt,
				failureCount: newState.fetchFailureCount,
				failureReason: newState.fetchFailureReason,
				errorUpdateCount: newState.errorUpdateCount,
				isFetched: query.isFetched(),
				isFetchedAfterMount: newState.dataUpdateCount > queryInitialState.dataUpdateCount || newState.errorUpdateCount > queryInitialState.errorUpdateCount,
				isFetching,
				isRefetching: isFetching && !isPending,
				isLoadingError: isError && !hasData,
				isPaused: newState.fetchStatus === "paused",
				isPlaceholderData,
				isRefetchError: isError && hasData,
				isStale: isStale(query, options),
				refetch: this.refetch,
				promise: this.#currentThenable,
				isEnabled: resolveQueryBoolean(options.enabled, query) !== false
			};
			if (this.options.experimental_prefetchInRender) {
				const hasResultData = nextResult.data !== void 0;
				const isErrorWithoutData = nextResult.status === "error" && !hasResultData;
				const finalizeThenableIfPossible = (thenable) => {
					if (isErrorWithoutData) thenable.reject(nextResult.error);
					else if (hasResultData) thenable.resolve(nextResult.data);
				};
				const recreateThenable = () => {
					const pending = this.#currentThenable = nextResult.promise = pendingThenable();
					finalizeThenableIfPossible(pending);
				};
				const prevThenable = this.#currentThenable;
				switch (prevThenable.status) {
					case "pending":
						if (query.queryHash === prevQuery.queryHash) finalizeThenableIfPossible(prevThenable);
						break;
					case "fulfilled":
						if (isErrorWithoutData || nextResult.data !== prevThenable.value) recreateThenable();
						break;
					case "rejected": if (!isErrorWithoutData || nextResult.error !== prevThenable.reason) recreateThenable();
				}
			}
			return nextResult;
		}
		updateResult() {
			const prevResult = this.#currentResult;
			const nextResult = this.createResult(this.#currentQuery, this.options);
			this.#currentResultState = this.#currentQuery.state;
			this.#currentResultOptions = this.options;
			if (this.#currentResultState.data !== void 0) this.#lastQueryWithDefinedData = this.#currentQuery;
			if (shallowEqualObjects(nextResult, prevResult)) return;
			this.#currentResult = nextResult;
			const shouldNotifyListeners = () => {
				if (!prevResult) return true;
				const { notifyOnChangeProps } = this.options;
				const notifyOnChangePropsValue = typeof notifyOnChangeProps === "function" ? notifyOnChangeProps() : notifyOnChangeProps;
				if (notifyOnChangePropsValue === "all" || !notifyOnChangePropsValue && !this.#trackedProps.size) return true;
				const includedProps = new Set(notifyOnChangePropsValue ?? this.#trackedProps);
				if (this.options.throwOnError) includedProps.add("error");
				return Object.keys(this.#currentResult).some((key) => {
					const typedKey = key;
					return this.#currentResult[typedKey] !== prevResult[typedKey] && includedProps.has(typedKey);
				});
			};
			this.#notify({ listeners: shouldNotifyListeners() });
		}
		#updateQuery() {
			const query = this.#client.getQueryCache().build(this.#client, this.options);
			if (query === this.#currentQuery) return;
			const prevQuery = this.#currentQuery;
			this.#currentQuery = query;
			this.#currentQueryInitialState = query.state;
			if (this.hasListeners()) {
				prevQuery?.removeObserver(this);
				query.addObserver(this);
			}
		}
		onQueryUpdate() {
			this.updateResult();
			if (this.hasListeners()) this.#updateTimers();
		}
		#notify(notifyOptions) {
			notifyManager.batch(() => {
				if (notifyOptions.listeners) this.listeners.forEach((listener) => {
					listener(this.#currentResult);
				});
				this.#client.getQueryCache().notify({
					query: this.#currentQuery,
					type: "observerResultsUpdated"
				});
			});
		}
	};
	function shouldLoadOnMount(query, options) {
		return resolveQueryBoolean(options.enabled, query) !== false && query.state.data === void 0 && !(query.state.status === "error" && resolveQueryBoolean(options.retryOnMount, query) === false);
	}
	function shouldFetchOnMount(query, options) {
		return shouldLoadOnMount(query, options) || query.state.data !== void 0 && shouldFetchOn(query, options, options.refetchOnMount);
	}
	function shouldFetchOn(query, options, field) {
		if (resolveQueryBoolean(options.enabled, query) !== false && resolveStaleTime(options.staleTime, query) !== "static") {
			const value = typeof field === "function" ? field(query) : field;
			return value === "always" || value !== false && isStale(query, options);
		}
		return false;
	}
	function shouldFetchOptionally(query, prevQuery, options, prevOptions) {
		return (query !== prevQuery || resolveQueryBoolean(prevOptions.enabled, query) === false) && (!options.suspense || query.state.status !== "error") && isStale(query, options);
	}
	function isStale(query, options) {
		return resolveQueryBoolean(options.enabled, query) !== false && query.isStaleByTime(resolveStaleTime(options.staleTime, query));
	}
	function shouldAssignObserverCurrentProperties(observer, optimisticResult) {
		if (!shallowEqualObjects(observer.getCurrentResult(), optimisticResult)) return true;
		return false;
	}
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/mutation.js
	var Mutation = class extends Removable {
		#client;
		#observers;
		#mutationCache;
		#retryer;
		constructor(config) {
			super();
			this.#client = config.client;
			this.mutationId = config.mutationId;
			this.#mutationCache = config.mutationCache;
			this.#observers = [];
			this.state = config.state || getDefaultState();
			this.setOptions(config.options);
			this.scheduleGc();
		}
		setOptions(options) {
			this.options = options;
			this.updateGcTime(this.options.gcTime);
		}
		get meta() {
			return this.options.meta;
		}
		addObserver(observer) {
			if (!this.#observers.includes(observer)) {
				this.#observers.push(observer);
				this.clearGcTimeout();
				this.#mutationCache.notify({
					type: "observerAdded",
					mutation: this,
					observer
				});
			}
		}
		removeObserver(observer) {
			this.#observers = this.#observers.filter((x) => x !== observer);
			this.scheduleGc();
			this.#mutationCache.notify({
				type: "observerRemoved",
				mutation: this,
				observer
			});
		}
		optionalRemove() {
			if (!this.#observers.length) {
				if (this.state.status === "pending") this.scheduleGc();
				else this.#mutationCache.remove(this);
			}
		}
		continue() {
			return this.#retryer?.continue() ?? this.execute(this.state.variables);
		}
		async execute(variables) {
			const onContinue = () => {
				this.#dispatch({ type: "continue" });
			};
			const mutationFnContext = {
				client: this.#client,
				meta: this.options.meta,
				mutationKey: this.options.mutationKey
			};
			this.#retryer = createRetryer({
				fn: () => {
					if (!this.options.mutationFn) return Promise.reject(/* @__PURE__ */ new Error("No mutationFn found"));
					return this.options.mutationFn(variables, mutationFnContext);
				},
				onFail: (failureCount, error) => {
					this.#dispatch({
						type: "failed",
						failureCount,
						error
					});
				},
				onPause: () => {
					this.#dispatch({ type: "pause" });
				},
				onContinue,
				retry: this.options.retry ?? 0,
				retryDelay: this.options.retryDelay,
				networkMode: this.options.networkMode,
				canRun: () => this.#mutationCache.canRun(this)
			});
			const restored = this.state.status === "pending";
			const isPaused = !this.#retryer.canStart();
			try {
				if (restored) onContinue();
				else {
					this.#dispatch({
						type: "pending",
						variables,
						isPaused
					});
					if (this.#mutationCache.config.onMutate) await this.#mutationCache.config.onMutate(variables, this, mutationFnContext);
					const context = await this.options.onMutate?.(variables, mutationFnContext);
					if (context !== this.state.context) this.#dispatch({
						type: "pending",
						context,
						variables,
						isPaused
					});
				}
				const data = await this.#retryer.start();
				await this.#mutationCache.config.onSuccess?.(data, variables, this.state.context, this, mutationFnContext);
				await this.options.onSuccess?.(data, variables, this.state.context, mutationFnContext);
				await this.#mutationCache.config.onSettled?.(data, null, this.state.variables, this.state.context, this, mutationFnContext);
				await this.options.onSettled?.(data, null, variables, this.state.context, mutationFnContext);
				this.#dispatch({
					type: "success",
					data
				});
				return data;
			} catch (error) {
				try {
					await this.#mutationCache.config.onError?.(error, variables, this.state.context, this, mutationFnContext);
				} catch (e) {
					Promise.reject(e);
				}
				try {
					await this.options.onError?.(error, variables, this.state.context, mutationFnContext);
				} catch (e) {
					Promise.reject(e);
				}
				try {
					await this.#mutationCache.config.onSettled?.(void 0, error, this.state.variables, this.state.context, this, mutationFnContext);
				} catch (e) {
					Promise.reject(e);
				}
				try {
					await this.options.onSettled?.(void 0, error, variables, this.state.context, mutationFnContext);
				} catch (e) {
					Promise.reject(e);
				}
				this.#dispatch({
					type: "error",
					error
				});
				throw error;
			} finally {
				this.#mutationCache.runNext(this);
			}
		}
		#dispatch(action) {
			const reducer = (state) => {
				switch (action.type) {
					case "failed": return {
						...state,
						failureCount: action.failureCount,
						failureReason: action.error
					};
					case "pause": return {
						...state,
						isPaused: true
					};
					case "continue": return {
						...state,
						isPaused: false
					};
					case "pending": return {
						...state,
						context: action.context,
						data: void 0,
						failureCount: 0,
						failureReason: null,
						error: null,
						isPaused: action.isPaused,
						status: "pending",
						variables: action.variables,
						submittedAt: Date.now()
					};
					case "success": return {
						...state,
						data: action.data,
						failureCount: 0,
						failureReason: null,
						error: null,
						status: "success",
						isPaused: false
					};
					case "error": return {
						...state,
						data: void 0,
						error: action.error,
						failureCount: state.failureCount + 1,
						failureReason: action.error,
						isPaused: false,
						status: "error"
					};
				}
			};
			this.state = reducer(this.state);
			notifyManager.batch(() => {
				this.#observers.forEach((observer) => {
					observer.onMutationUpdate(action);
				});
				this.#mutationCache.notify({
					mutation: this,
					type: "updated",
					action
				});
			});
		}
	};
	function getDefaultState() {
		return {
			context: void 0,
			data: void 0,
			error: null,
			failureCount: 0,
			failureReason: null,
			isPaused: false,
			status: "idle",
			variables: void 0,
			submittedAt: 0
		};
	}
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/mutationCache.js
	var MutationCache$1 = class extends Subscribable {
		constructor(config = {}) {
			super();
			this.config = config;
			this.#mutations = /* @__PURE__ */ new Set();
			this.#scopes = /* @__PURE__ */ new Map();
			this.#mutationId = 0;
		}
		#mutations;
		#scopes;
		#mutationId;
		build(client, options, state) {
			const mutation = new Mutation({
				client,
				mutationCache: this,
				mutationId: ++this.#mutationId,
				options: client.defaultMutationOptions(options),
				state
			});
			this.add(mutation);
			return mutation;
		}
		add(mutation) {
			this.#mutations.add(mutation);
			const scope = scopeFor(mutation);
			if (typeof scope === "string") {
				const scopedMutations = this.#scopes.get(scope);
				if (scopedMutations) scopedMutations.push(mutation);
				else this.#scopes.set(scope, [mutation]);
			}
			this.notify({
				type: "added",
				mutation
			});
		}
		remove(mutation) {
			if (this.#mutations.delete(mutation)) {
				const scope = scopeFor(mutation);
				if (typeof scope === "string") {
					const scopedMutations = this.#scopes.get(scope);
					if (scopedMutations) {
						if (scopedMutations.length > 1) {
							const index = scopedMutations.indexOf(mutation);
							if (index !== -1) scopedMutations.splice(index, 1);
						} else if (scopedMutations[0] === mutation) this.#scopes.delete(scope);
					}
				}
			}
			this.notify({
				type: "removed",
				mutation
			});
		}
		canRun(mutation) {
			const scope = scopeFor(mutation);
			if (typeof scope === "string") {
				const firstPendingMutation = this.#scopes.get(scope)?.find((m) => m.state.status === "pending");
				return !firstPendingMutation || firstPendingMutation === mutation;
			} else return true;
		}
		runNext(mutation) {
			const scope = scopeFor(mutation);
			if (typeof scope === "string") return (this.#scopes.get(scope)?.find((m) => m !== mutation && m.state.isPaused))?.continue() ?? Promise.resolve();
			else return Promise.resolve();
		}
		clear() {
			notifyManager.batch(() => {
				this.#mutations.forEach((mutation) => {
					this.notify({
						type: "removed",
						mutation
					});
				});
				this.#mutations.clear();
				this.#scopes.clear();
			});
		}
		getAll() {
			return Array.from(this.#mutations);
		}
		find(filters) {
			const defaultedFilters = {
				exact: true,
				...filters
			};
			return this.getAll().find((mutation) => matchMutation(defaultedFilters, mutation));
		}
		findAll(filters = {}) {
			return this.getAll().filter((mutation) => matchMutation(filters, mutation));
		}
		notify(event) {
			notifyManager.batch(() => {
				this.listeners.forEach((listener) => {
					listener(event);
				});
			});
		}
		resumePausedMutations() {
			const pausedMutations = this.getAll().filter((x) => x.state.isPaused);
			return notifyManager.batch(() => Promise.all(pausedMutations.map((mutation) => mutation.continue().catch(noop$2))));
		}
	};
	function scopeFor(mutation) {
		return mutation.options.scope?.id;
	}
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/mutationObserver.js
	var MutationObserver$1 = class extends Subscribable {
		#client;
		#currentResult = void 0;
		#currentMutation;
		#mutateOptions;
		constructor(client, options) {
			super();
			this.#client = client;
			this.setOptions(options);
			this.bindMethods();
			this.#updateResult();
		}
		bindMethods() {
			this.mutate = this.mutate.bind(this);
			this.reset = this.reset.bind(this);
		}
		setOptions(options) {
			const prevOptions = this.options;
			this.options = this.#client.defaultMutationOptions(options);
			if (!shallowEqualObjects(this.options, prevOptions)) this.#client.getMutationCache().notify({
				type: "observerOptionsUpdated",
				mutation: this.#currentMutation,
				observer: this
			});
			if (prevOptions?.mutationKey && this.options.mutationKey && hashKey(prevOptions.mutationKey) !== hashKey(this.options.mutationKey)) this.reset();
			else if (this.#currentMutation?.state.status === "pending") this.#currentMutation.setOptions(this.options);
		}
		onUnsubscribe() {
			if (!this.hasListeners()) this.#currentMutation?.removeObserver(this);
		}
		onMutationUpdate(action) {
			this.#updateResult();
			this.#notify(action);
		}
		getCurrentResult() {
			return this.#currentResult;
		}
		reset() {
			this.#currentMutation?.removeObserver(this);
			this.#currentMutation = void 0;
			this.#updateResult();
			this.#notify();
		}
		mutate(variables, options) {
			this.#mutateOptions = options;
			this.#currentMutation?.removeObserver(this);
			this.#currentMutation = this.#client.getMutationCache().build(this.#client, this.options);
			this.#currentMutation.addObserver(this);
			return this.#currentMutation.execute(variables);
		}
		#updateResult() {
			const state = this.#currentMutation?.state ?? getDefaultState();
			this.#currentResult = {
				...state,
				isPending: state.status === "pending",
				isSuccess: state.status === "success",
				isError: state.status === "error",
				isIdle: state.status === "idle",
				mutate: this.mutate,
				reset: this.reset
			};
		}
		#notify(action) {
			notifyManager.batch(() => {
				if (this.#mutateOptions && this.hasListeners()) {
					const variables = this.#currentResult.variables;
					const onMutateResult = this.#currentResult.context;
					const context = {
						client: this.#client,
						meta: this.options.meta,
						mutationKey: this.options.mutationKey
					};
					if (action?.type === "success") {
						try {
							this.#mutateOptions.onSuccess?.(action.data, variables, onMutateResult, context);
						} catch (e) {
							Promise.reject(e);
						}
						try {
							this.#mutateOptions.onSettled?.(action.data, null, variables, onMutateResult, context);
						} catch (e) {
							Promise.reject(e);
						}
					} else if (action?.type === "error") {
						try {
							this.#mutateOptions.onError?.(action.error, variables, onMutateResult, context);
						} catch (e) {
							Promise.reject(e);
						}
						try {
							this.#mutateOptions.onSettled?.(void 0, action.error, variables, onMutateResult, context);
						} catch (e) {
							Promise.reject(e);
						}
					}
				}
				this.listeners.forEach((listener) => {
					listener(this.#currentResult);
				});
			});
		}
	};
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/queryCache.js
	var QueryCache$1 = class extends Subscribable {
		constructor(config = {}) {
			super();
			this.config = config;
			this.#queries = /* @__PURE__ */ new Map();
		}
		#queries;
		build(client, options, state) {
			const queryKey = options.queryKey;
			const queryHash = options.queryHash ?? hashQueryKeyByOptions(queryKey, options);
			let query = this.get(queryHash);
			if (!query) {
				query = new Query({
					client,
					queryKey,
					queryHash,
					options: client.defaultQueryOptions(options),
					state,
					defaultOptions: client.getQueryDefaults(queryKey)
				});
				this.add(query);
			}
			return query;
		}
		add(query) {
			if (!this.#queries.has(query.queryHash)) {
				this.#queries.set(query.queryHash, query);
				this.notify({
					type: "added",
					query
				});
			}
		}
		remove(query) {
			const queryInMap = this.#queries.get(query.queryHash);
			if (queryInMap) {
				query.destroy();
				if (queryInMap === query) this.#queries.delete(query.queryHash);
				this.notify({
					type: "removed",
					query
				});
			}
		}
		clear() {
			notifyManager.batch(() => {
				this.getAll().forEach((query) => {
					this.remove(query);
				});
			});
		}
		get(queryHash) {
			return this.#queries.get(queryHash);
		}
		getAll() {
			return [...this.#queries.values()];
		}
		find(filters) {
			const defaultedFilters = {
				exact: true,
				...filters
			};
			return this.getAll().find((query) => matchQuery(defaultedFilters, query));
		}
		findAll(filters = {}) {
			const queries = this.getAll();
			return Object.keys(filters).length > 0 ? queries.filter((query) => matchQuery(filters, query)) : queries;
		}
		notify(event) {
			notifyManager.batch(() => {
				this.listeners.forEach((listener) => {
					listener(event);
				});
			});
		}
		onFocus() {
			notifyManager.batch(() => {
				this.getAll().forEach((query) => {
					query.onFocus();
				});
			});
		}
		onOnline() {
			notifyManager.batch(() => {
				this.getAll().forEach((query) => {
					query.onOnline();
				});
			});
		}
	};
	//#endregion
	//#region node_modules/@tanstack/query-core/build/modern/queryClient.js
	var QueryClient$1 = class {
		#queryCache;
		#mutationCache;
		#defaultOptions;
		#queryDefaults;
		#mutationDefaults;
		#mountCount;
		#unsubscribeFocus;
		#unsubscribeOnline;
		constructor(config = {}) {
			this.#queryCache = config.queryCache || new QueryCache$1();
			this.#mutationCache = config.mutationCache || new MutationCache$1();
			this.#defaultOptions = config.defaultOptions || {};
			this.#queryDefaults = /* @__PURE__ */ new Map();
			this.#mutationDefaults = /* @__PURE__ */ new Map();
			this.#mountCount = 0;
		}
		mount() {
			this.#mountCount++;
			if (this.#mountCount !== 1) return;
			this.#unsubscribeFocus = focusManager.subscribe(async (focused) => {
				if (focused) {
					await this.resumePausedMutations();
					this.#queryCache.onFocus();
				}
			});
			this.#unsubscribeOnline = onlineManager.subscribe(async (online) => {
				if (online) {
					await this.resumePausedMutations();
					this.#queryCache.onOnline();
				}
			});
		}
		unmount() {
			this.#mountCount--;
			if (this.#mountCount !== 0) return;
			this.#unsubscribeFocus?.();
			this.#unsubscribeFocus = void 0;
			this.#unsubscribeOnline?.();
			this.#unsubscribeOnline = void 0;
		}
		isFetching(filters) {
			return this.#queryCache.findAll({
				...filters,
				fetchStatus: "fetching"
			}).length;
		}
		isMutating(filters) {
			return this.#mutationCache.findAll({
				...filters,
				status: "pending"
			}).length;
		}
		/**
		* Imperative (non-reactive) way to retrieve data for a QueryKey.
		* Should only be used in callbacks or functions where reading the latest data is necessary, e.g. for optimistic updates.
		*
		* Hint: Do not use this function inside a component, because it won't receive updates.
		* Use `useQuery` to create a `QueryObserver` that subscribes to changes.
		*/
		getQueryData(queryKey) {
			const options = this.defaultQueryOptions({ queryKey });
			return this.#queryCache.get(options.queryHash)?.state.data;
		}
		ensureQueryData(options) {
			const defaultedOptions = this.defaultQueryOptions(options);
			const query = this.#queryCache.build(this, defaultedOptions);
			const cachedData = query.state.data;
			if (cachedData === void 0) return this.fetchQuery(options);
			if (options.revalidateIfStale && query.isStaleByTime(resolveStaleTime(defaultedOptions.staleTime, query))) this.prefetchQuery(defaultedOptions);
			return Promise.resolve(cachedData);
		}
		getQueriesData(filters) {
			return this.#queryCache.findAll(filters).map(({ queryKey, state }) => {
				return [queryKey, state.data];
			});
		}
		setQueryData(queryKey, updater, options) {
			const defaultedOptions = this.defaultQueryOptions({ queryKey });
			const prevData = this.#queryCache.get(defaultedOptions.queryHash)?.state.data;
			const data = functionalUpdate(updater, prevData);
			if (data === void 0) return;
			return this.#queryCache.build(this, defaultedOptions).setData(data, {
				...options,
				manual: true
			});
		}
		setQueriesData(filters, updater, options) {
			return notifyManager.batch(() => this.#queryCache.findAll(filters).map(({ queryKey }) => [queryKey, this.setQueryData(queryKey, updater, options)]));
		}
		getQueryState(queryKey) {
			const options = this.defaultQueryOptions({ queryKey });
			return this.#queryCache.get(options.queryHash)?.state;
		}
		removeQueries(filters) {
			const queryCache = this.#queryCache;
			notifyManager.batch(() => {
				queryCache.findAll(filters).forEach((query) => {
					queryCache.remove(query);
				});
			});
		}
		resetQueries(filters, options) {
			const queryCache = this.#queryCache;
			return notifyManager.batch(() => {
				queryCache.findAll(filters).forEach((query) => {
					query.reset();
				});
				return this.refetchQueries({
					type: "active",
					...filters
				}, options);
			});
		}
		cancelQueries(filters, cancelOptions = {}) {
			const defaultedCancelOptions = {
				revert: true,
				...cancelOptions
			};
			const promises = notifyManager.batch(() => this.#queryCache.findAll(filters).map((query) => query.cancel(defaultedCancelOptions)));
			return Promise.all(promises).then(noop$2).catch(noop$2);
		}
		invalidateQueries(filters, options = {}) {
			return notifyManager.batch(() => {
				this.#queryCache.findAll(filters).forEach((query) => {
					query.invalidate();
				});
				if (filters?.refetchType === "none") return Promise.resolve();
				return this.refetchQueries({
					...filters,
					type: filters?.refetchType ?? filters?.type ?? "active"
				}, options);
			});
		}
		refetchQueries(filters, options = {}) {
			const fetchOptions = {
				...options,
				cancelRefetch: options.cancelRefetch ?? true
			};
			const promises = notifyManager.batch(() => this.#queryCache.findAll(filters).filter((query) => !query.isDisabled() && !query.isStatic()).map((query) => {
				let promise = query.fetch(void 0, fetchOptions);
				if (!fetchOptions.throwOnError) promise = promise.catch(noop$2);
				return query.state.fetchStatus === "paused" ? Promise.resolve() : promise;
			}));
			return Promise.all(promises).then(noop$2);
		}
		fetchQuery(options) {
			const defaultedOptions = this.defaultQueryOptions(options);
			if (defaultedOptions.retry === void 0) defaultedOptions.retry = false;
			const query = this.#queryCache.build(this, defaultedOptions);
			return query.isStaleByTime(resolveStaleTime(defaultedOptions.staleTime, query)) ? query.fetch(defaultedOptions) : Promise.resolve(query.state.data);
		}
		prefetchQuery(options) {
			return this.fetchQuery(options).then(noop$2).catch(noop$2);
		}
		fetchInfiniteQuery(options) {
			options._type = "infinite";
			return this.fetchQuery(options);
		}
		prefetchInfiniteQuery(options) {
			return this.fetchInfiniteQuery(options).then(noop$2).catch(noop$2);
		}
		ensureInfiniteQueryData(options) {
			options._type = "infinite";
			return this.ensureQueryData(options);
		}
		resumePausedMutations() {
			if (onlineManager.isOnline()) return this.#mutationCache.resumePausedMutations();
			return Promise.resolve();
		}
		getQueryCache() {
			return this.#queryCache;
		}
		getMutationCache() {
			return this.#mutationCache;
		}
		getDefaultOptions() {
			return this.#defaultOptions;
		}
		setDefaultOptions(options) {
			this.#defaultOptions = options;
		}
		setQueryDefaults(queryKey, options) {
			this.#queryDefaults.set(hashKey(queryKey), {
				queryKey,
				defaultOptions: options
			});
		}
		getQueryDefaults(queryKey) {
			const defaults = [...this.#queryDefaults.values()];
			const result = {};
			defaults.forEach((queryDefault) => {
				if (partialMatchKey(queryKey, queryDefault.queryKey)) Object.assign(result, queryDefault.defaultOptions);
			});
			return result;
		}
		setMutationDefaults(mutationKey, options) {
			this.#mutationDefaults.set(hashKey(mutationKey), {
				mutationKey,
				defaultOptions: options
			});
		}
		getMutationDefaults(mutationKey) {
			const defaults = [...this.#mutationDefaults.values()];
			const result = {};
			defaults.forEach((queryDefault) => {
				if (partialMatchKey(mutationKey, queryDefault.mutationKey)) Object.assign(result, queryDefault.defaultOptions);
			});
			return result;
		}
		defaultQueryOptions(options) {
			if (options._defaulted) return options;
			const defaultedOptions = {
				...this.#defaultOptions.queries,
				...this.getQueryDefaults(options.queryKey),
				...options,
				_defaulted: true
			};
			if (!defaultedOptions.queryHash) defaultedOptions.queryHash = hashQueryKeyByOptions(defaultedOptions.queryKey, defaultedOptions);
			if (defaultedOptions.refetchOnReconnect === void 0) defaultedOptions.refetchOnReconnect = defaultedOptions.networkMode !== "always";
			if (defaultedOptions.throwOnError === void 0) defaultedOptions.throwOnError = !!defaultedOptions.suspense;
			if (!defaultedOptions.networkMode && defaultedOptions.persister) defaultedOptions.networkMode = "offlineFirst";
			if (defaultedOptions.queryFn === skipToken) defaultedOptions.enabled = false;
			return defaultedOptions;
		}
		defaultMutationOptions(options) {
			if (options?._defaulted) return options;
			return {
				...this.#defaultOptions.mutations,
				...options?.mutationKey && this.getMutationDefaults(options.mutationKey),
				...options,
				_defaulted: true
			};
		}
		clear() {
			this.#queryCache.clear();
			this.#mutationCache.clear();
		}
	};
	//#endregion
	//#region node_modules/@vue/shared/dist/shared.esm-bundler.js
	/**
	* @vue/shared v3.5.41
	* (c) 2018-present Yuxi (Evan) You and Vue contributors
	* @license MIT
	**/
	// @__NO_SIDE_EFFECTS__
	function makeMap(str) {
		const map = /* @__PURE__ */ Object.create(null);
		for (const key of str.split(",")) map[key] = 1;
		return (val) => val in map;
	}
	var EMPTY_OBJ = {};
	var EMPTY_ARR = [];
	var NOOP = () => {};
	var NO = () => false;
	var isOn = (key) => key.charCodeAt(0) === 111 && key.charCodeAt(1) === 110 && (key.charCodeAt(2) > 122 || key.charCodeAt(2) < 97);
	var isModelListener = (key) => key.startsWith("onUpdate:");
	var extend = Object.assign;
	var remove = (arr, el) => {
		const i = arr.indexOf(el);
		if (i > -1) arr.splice(i, 1);
	};
	var hasOwnProperty$1 = Object.prototype.hasOwnProperty;
	var hasOwn = (val, key) => hasOwnProperty$1.call(val, key);
	var isArray$1 = Array.isArray;
	var isMap = (val) => toTypeString(val) === "[object Map]";
	var isSet = (val) => toTypeString(val) === "[object Set]";
	var isDate = (val) => toTypeString(val) === "[object Date]";
	var isFunction$1 = (val) => typeof val === "function";
	var isString = (val) => typeof val === "string";
	var isSymbol = (val) => typeof val === "symbol";
	var isObject = (val) => val !== null && typeof val === "object";
	var isPromise = (val) => {
		return (isObject(val) || isFunction$1(val)) && isFunction$1(val.then) && isFunction$1(val.catch);
	};
	var objectToString = Object.prototype.toString;
	var toTypeString = (value) => objectToString.call(value);
	var toRawType = (value) => {
		return toTypeString(value).slice(8, -1);
	};
	var isPlainObject$2 = (val) => toTypeString(val) === "[object Object]";
	var isIntegerKey = (key) => isString(key) && key !== "NaN" && key[0] !== "-" && "" + parseInt(key, 10) === key;
	var isReservedProp = /* @__PURE__ */ makeMap(",key,ref,ref_for,ref_key,onVnodeBeforeMount,onVnodeMounted,onVnodeBeforeUpdate,onVnodeUpdated,onVnodeBeforeUnmount,onVnodeUnmounted");
	var cacheStringFunction = (fn) => {
		const cache = /* @__PURE__ */ Object.create(null);
		return ((str) => {
			return cache[str] || (cache[str] = fn(str));
		});
	};
	var camelizeRE = /-\w/g;
	var camelize = cacheStringFunction((str) => {
		return str.replace(camelizeRE, (c) => c.slice(1).toUpperCase());
	});
	var hyphenateRE = /\B([A-Z])/g;
	var hyphenate = cacheStringFunction((str) => str.replace(hyphenateRE, "-$1").toLowerCase());
	var capitalize = cacheStringFunction((str) => {
		return str.charAt(0).toUpperCase() + str.slice(1);
	});
	var toHandlerKey = cacheStringFunction((str) => {
		return str ? `on${capitalize(str)}` : ``;
	});
	var hasChanged = (value, oldValue) => !Object.is(value, oldValue);
	var invokeArrayFns = (fns, ...arg) => {
		for (let i = 0; i < fns.length; i++) fns[i](...arg);
	};
	var def = (obj, key, value, writable = false) => {
		Object.defineProperty(obj, key, {
			configurable: true,
			enumerable: false,
			writable,
			value
		});
	};
	var looseToNumber = (val) => {
		const n = parseFloat(val);
		return isNaN(n) ? val : n;
	};
	var _globalThis;
	var getGlobalThis = () => {
		return _globalThis || (_globalThis = typeof globalThis !== "undefined" ? globalThis : typeof self !== "undefined" ? self : typeof window !== "undefined" ? window : typeof global !== "undefined" ? global : {});
	};
	function normalizeStyle(value) {
		if (isArray$1(value)) {
			const res = {};
			for (let i = 0; i < value.length; i++) {
				const item = value[i];
				const normalized = isString(item) ? parseStringStyle(item) : normalizeStyle(item);
				if (normalized) for (const key in normalized) res[key] = normalized[key];
			}
			return res;
		} else if (isString(value) || isObject(value)) return value;
	}
	var listDelimiterRE = /;(?![^(]*\))/g;
	var propertyDelimiterRE = /:([^]+)/;
	var styleCommentRE = /\/\*[^]*?\*\//g;
	function parseStringStyle(cssText) {
		const ret = {};
		cssText.replace(styleCommentRE, "").split(listDelimiterRE).forEach((item) => {
			if (item) {
				const tmp = item.split(propertyDelimiterRE);
				tmp.length > 1 && (ret[tmp[0].trim()] = tmp[1].trim());
			}
		});
		return ret;
	}
	function normalizeClass(value) {
		let res = "";
		if (isString(value)) res = value;
		else if (isArray$1(value)) for (let i = 0; i < value.length; i++) {
			const normalized = normalizeClass(value[i]);
			if (normalized) res += normalized + " ";
		}
		else if (isObject(value)) {
			for (const name in value) if (value[name]) res += name + " ";
		}
		return res.trim();
	}
	var specialBooleanAttrs = `itemscope,allowfullscreen,formnovalidate,ismap,nomodule,novalidate,readonly`;
	var isSpecialBooleanAttr = /* @__PURE__ */ makeMap(specialBooleanAttrs);
	specialBooleanAttrs + "";
	function includeBooleanAttr(value) {
		return !!value || value === "";
	}
	function looseCompareArrays(a, b) {
		if (a.length !== b.length) return false;
		let equal = true;
		for (let i = 0; equal && i < a.length; i++) equal = looseEqual(a[i], b[i]);
		return equal;
	}
	function looseEqual(a, b) {
		if (a === b) return true;
		let aValidType = isDate(a);
		let bValidType = isDate(b);
		if (aValidType || bValidType) return aValidType && bValidType ? a.getTime() === b.getTime() : false;
		aValidType = isSymbol(a);
		bValidType = isSymbol(b);
		if (aValidType || bValidType) return a === b;
		aValidType = isArray$1(a);
		bValidType = isArray$1(b);
		if (aValidType || bValidType) return aValidType && bValidType ? looseCompareArrays(a, b) : false;
		aValidType = isObject(a);
		bValidType = isObject(b);
		if (aValidType || bValidType) {
			if (!aValidType || !bValidType) return false;
			if (Object.keys(a).length !== Object.keys(b).length) return false;
			for (const key in a) {
				const aHasKey = a.hasOwnProperty(key);
				const bHasKey = b.hasOwnProperty(key);
				if (aHasKey && !bHasKey || !aHasKey && bHasKey || !looseEqual(a[key], b[key])) return false;
			}
		}
		return String(a) === String(b);
	}
	var isRef$1 = (val) => {
		return !!(val && val["__v_isRef"] === true);
	};
	var toDisplayString = (val) => {
		return isString(val) ? val : val == null ? "" : isArray$1(val) || isObject(val) && (val.toString === objectToString || !isFunction$1(val.toString)) ? isRef$1(val) ? toDisplayString(val.value) : JSON.stringify(val, replacer, 2) : String(val);
	};
	var replacer = (_key, val) => {
		if (isRef$1(val)) return replacer(_key, val.value);
		else if (isMap(val)) return { [`Map(${val.size})`]: [...val.entries()].reduce((entries, [key, val2], i) => {
			entries[stringifySymbol(key, i) + " =>"] = val2;
			return entries;
		}, {}) };
		else if (isSet(val)) return { [`Set(${val.size})`]: [...val.values()].map((v) => stringifySymbol(v)) };
		else if (isSymbol(val)) return stringifySymbol(val);
		else if (isObject(val) && !isArray$1(val) && !isPlainObject$2(val)) return String(val);
		return val;
	};
	var stringifySymbol = (v, i = "") => {
		var _a;
		return isSymbol(v) ? `Symbol(${(_a = v.description) != null ? _a : i})` : v;
	};
	//#endregion
	//#region node_modules/@vue/reactivity/dist/reactivity.esm-bundler.js
	/**
	* @vue/reactivity v3.5.41
	* (c) 2018-present Yuxi (Evan) You and Vue contributors
	* @license MIT
	**/
	var activeEffectScope;
	var EffectScope = class {
		constructor(detached = false) {
			this.detached = detached;
			/**
			* @internal
			*/
			this._active = true;
			/**
			* @internal track `on` calls, allow `on` call multiple times
			*/
			this._on = 0;
			/**
			* @internal
			*/
			this.effects = [];
			/**
			* @internal
			*/
			this.cleanups = [];
			this._isPaused = false;
			this._warnOnRun = true;
			this.__v_skip = true;
			if (!detached && activeEffectScope) {
				if (activeEffectScope.active) {
					this.parent = activeEffectScope;
					this.index = (activeEffectScope.scopes || (activeEffectScope.scopes = [])).push(this) - 1;
				} else {
					this._active = false;
					this._warnOnRun = false;
				}
			}
		}
		get active() {
			return this._active;
		}
		pause() {
			if (this._active) {
				this._isPaused = true;
				let i, l;
				if (this.scopes) {
					const scopes = this.scopes.slice();
					for (i = 0, l = scopes.length; i < l; i++) scopes[i].pause();
				}
				for (i = 0, l = this.effects.length; i < l; i++) this.effects[i].pause();
			}
		}
		/**
		* Resumes the effect scope, including all child scopes and effects.
		*/
		resume() {
			if (this._active) {
				if (this._isPaused) {
					this._isPaused = false;
					let i, l;
					if (this.scopes) {
						const scopes = this.scopes.slice();
						for (i = 0, l = scopes.length; i < l; i++) scopes[i].resume();
					}
					const effects = this.effects.slice();
					for (i = 0, l = effects.length; i < l; i++) effects[i].resume();
				}
			}
		}
		run(fn) {
			if (this._active) {
				const currentEffectScope = activeEffectScope;
				try {
					activeEffectScope = this;
					return fn();
				} finally {
					activeEffectScope = currentEffectScope;
				}
			}
		}
		/**
		* This should only be called on non-detached scopes
		* @internal
		*/
		on() {
			if (++this._on === 1) {
				this.prevScope = activeEffectScope;
				activeEffectScope = this;
			}
		}
		/**
		* This should only be called on non-detached scopes
		* @internal
		*/
		off() {
			if (this._on > 0 && --this._on === 0) {
				if (activeEffectScope === this) activeEffectScope = this.prevScope;
				else {
					let current = activeEffectScope;
					while (current) {
						if (current.prevScope === this) {
							current.prevScope = this.prevScope;
							break;
						}
						current = current.prevScope;
					}
				}
				this.prevScope = void 0;
			}
		}
		stop(fromParent) {
			if (this._active) {
				this._active = false;
				let i, l;
				for (i = 0, l = this.effects.length; i < l; i++) this.effects[i].stop();
				this.effects.length = 0;
				for (i = 0, l = this.cleanups.length; i < l; i++) this.cleanups[i]();
				this.cleanups.length = 0;
				if (this.scopes) {
					const scopes = this.scopes.slice();
					for (i = 0, l = scopes.length; i < l; i++) scopes[i].stop(true);
					this.scopes.length = 0;
				}
				if (!this.detached && this.parent && !fromParent) {
					const last = this.parent.scopes.pop();
					if (last && last !== this) {
						this.parent.scopes[this.index] = last;
						last.index = this.index;
					}
				}
				this.parent = void 0;
			}
		}
	};
	function effectScope(detached) {
		return new EffectScope(detached);
	}
	function getCurrentScope() {
		return activeEffectScope;
	}
	function onScopeDispose(fn, failSilently = false) {
		if (activeEffectScope) activeEffectScope.cleanups.push(fn);
	}
	var activeSub;
	var pausedQueueEffects = /* @__PURE__ */ new WeakSet();
	var ReactiveEffect = class {
		constructor(fn) {
			this.fn = fn;
			/**
			* @internal
			*/
			this.deps = void 0;
			/**
			* @internal
			*/
			this.depsTail = void 0;
			/**
			* @internal
			*/
			this.flags = 5;
			/**
			* @internal
			*/
			this.next = void 0;
			/**
			* @internal
			*/
			this.cleanup = void 0;
			this.scheduler = void 0;
			if (activeEffectScope) {
				if (activeEffectScope.active) activeEffectScope.effects.push(this);
				else this.flags &= -2;
			}
		}
		pause() {
			this.flags |= 64;
		}
		resume() {
			if (this.flags & 64) {
				this.flags &= -65;
				if (pausedQueueEffects.has(this)) {
					pausedQueueEffects.delete(this);
					this.trigger();
				}
			}
		}
		/**
		* @internal
		*/
		notify() {
			if (this.flags & 2 && !(this.flags & 32)) return;
			if (!(this.flags & 8)) batch(this);
		}
		run() {
			if (!(this.flags & 1)) return this.fn();
			this.flags |= 2;
			cleanupEffect(this);
			prepareDeps(this);
			const prevEffect = activeSub;
			const prevShouldTrack = shouldTrack;
			activeSub = this;
			shouldTrack = true;
			try {
				return this.fn();
			} finally {
				cleanupDeps(this);
				activeSub = prevEffect;
				shouldTrack = prevShouldTrack;
				this.flags &= -3;
			}
		}
		stop() {
			if (this.flags & 1) {
				for (let link = this.deps; link; link = link.nextDep) removeSub(link);
				this.deps = this.depsTail = void 0;
				cleanupEffect(this);
				this.onStop && this.onStop();
				this.flags &= -2;
			}
		}
		trigger() {
			if (this.flags & 64) pausedQueueEffects.add(this);
			else if (this.scheduler) this.scheduler();
			else this.runIfDirty();
		}
		/**
		* @internal
		*/
		runIfDirty() {
			if (isDirty(this)) this.run();
		}
		get dirty() {
			return isDirty(this);
		}
	};
	var batchDepth = 0;
	var batchedSub;
	var batchedComputed;
	function batch(sub, isComputed = false) {
		sub.flags |= 8;
		if (isComputed) {
			sub.next = batchedComputed;
			batchedComputed = sub;
			return;
		}
		sub.next = batchedSub;
		batchedSub = sub;
	}
	function startBatch() {
		batchDepth++;
	}
	function endBatch() {
		if (--batchDepth > 0) return;
		if (batchedComputed) {
			let e = batchedComputed;
			batchedComputed = void 0;
			while (e) {
				const next = e.next;
				e.next = void 0;
				e.flags &= -9;
				e = next;
			}
		}
		let error;
		while (batchedSub) {
			let e = batchedSub;
			batchedSub = void 0;
			while (e) {
				const next = e.next;
				e.next = void 0;
				e.flags &= -9;
				if (e.flags & 1) try {
					e.trigger();
				} catch (err) {
					if (!error) error = err;
				}
				e = next;
			}
		}
		if (error) throw error;
	}
	function prepareDeps(sub) {
		for (let link = sub.deps; link; link = link.nextDep) {
			link.version = -1;
			link.prevActiveLink = link.dep.activeLink;
			link.dep.activeLink = link;
		}
	}
	function cleanupDeps(sub) {
		let head;
		let tail = sub.depsTail;
		let link = tail;
		while (link) {
			const prev = link.prevDep;
			if (link.version === -1) {
				if (link === tail) tail = prev;
				removeSub(link);
				removeDep(link);
			} else head = link;
			link.dep.activeLink = link.prevActiveLink;
			link.prevActiveLink = void 0;
			link = prev;
		}
		sub.deps = head;
		sub.depsTail = tail;
	}
	function isDirty(sub) {
		for (let link = sub.deps; link; link = link.nextDep) if (link.dep.version !== link.version || link.dep.computed && (refreshComputed(link.dep.computed) || link.dep.version !== link.version)) return true;
		if (sub._dirty) return true;
		return false;
	}
	function refreshComputed(computed) {
		if (computed.flags & 4 && !(computed.flags & 16)) return;
		computed.flags &= -17;
		if (computed.globalVersion === globalVersion) return;
		computed.globalVersion = globalVersion;
		if (!computed.isSSR && computed.flags & 128 && (!computed.deps && !computed._dirty || !isDirty(computed))) return;
		computed.flags |= 2;
		const dep = computed.dep;
		const prevSub = activeSub;
		const prevShouldTrack = shouldTrack;
		activeSub = computed;
		shouldTrack = true;
		try {
			prepareDeps(computed);
			const value = computed.fn(computed._value);
			if (dep.version === 0 || hasChanged(value, computed._value)) {
				computed.flags |= 128;
				computed._value = value;
				dep.version++;
			}
		} catch (err) {
			dep.version++;
			throw err;
		} finally {
			activeSub = prevSub;
			shouldTrack = prevShouldTrack;
			cleanupDeps(computed);
			computed.flags &= -3;
		}
	}
	function removeSub(link, soft = false) {
		const { dep, prevSub, nextSub } = link;
		if (prevSub) {
			prevSub.nextSub = nextSub;
			link.prevSub = void 0;
		}
		if (nextSub) {
			nextSub.prevSub = prevSub;
			link.nextSub = void 0;
		}
		if (dep.subs === link) {
			dep.subs = prevSub;
			if (!prevSub && dep.computed) {
				dep.computed.flags &= -5;
				for (let l = dep.computed.deps; l; l = l.nextDep) removeSub(l, true);
			}
		}
		if (!soft && !--dep.sc && dep.map) dep.map.delete(dep.key);
	}
	function removeDep(link) {
		const { prevDep, nextDep } = link;
		if (prevDep) {
			prevDep.nextDep = nextDep;
			link.prevDep = void 0;
		}
		if (nextDep) {
			nextDep.prevDep = prevDep;
			link.nextDep = void 0;
		}
	}
	var shouldTrack = true;
	var trackStack = [];
	function pauseTracking() {
		trackStack.push(shouldTrack);
		shouldTrack = false;
	}
	function resetTracking() {
		const last = trackStack.pop();
		shouldTrack = last === void 0 ? true : last;
	}
	function cleanupEffect(e) {
		const { cleanup } = e;
		e.cleanup = void 0;
		if (cleanup) {
			const prevSub = activeSub;
			activeSub = void 0;
			try {
				cleanup();
			} finally {
				activeSub = prevSub;
			}
		}
	}
	var globalVersion = 0;
	var Link = class {
		constructor(sub, dep) {
			this.sub = sub;
			this.dep = dep;
			this.version = dep.version;
			this.nextDep = this.prevDep = this.nextSub = this.prevSub = this.prevActiveLink = void 0;
		}
	};
	var Dep = class {
		constructor(computed) {
			this.computed = computed;
			this.version = 0;
			/**
			* Link between this dep and the current active effect
			*/
			this.activeLink = void 0;
			/**
			* Doubly linked list representing the subscribing effects (tail)
			*/
			this.subs = void 0;
			/**
			* For object property deps cleanup
			*/
			this.map = void 0;
			this.key = void 0;
			/**
			* Subscriber counter
			*/
			this.sc = 0;
			/**
			* @internal
			*/
			this.__v_skip = true;
		}
		track(debugInfo) {
			if (!activeSub || !shouldTrack || activeSub === this.computed) return;
			let link = this.activeLink;
			if (link === void 0 || link.sub !== activeSub) {
				link = this.activeLink = new Link(activeSub, this);
				if (!activeSub.deps) activeSub.deps = activeSub.depsTail = link;
				else {
					link.prevDep = activeSub.depsTail;
					activeSub.depsTail.nextDep = link;
					activeSub.depsTail = link;
				}
				addSub(link);
			} else if (link.version === -1) {
				link.version = this.version;
				if (link.nextDep) {
					const next = link.nextDep;
					next.prevDep = link.prevDep;
					if (link.prevDep) link.prevDep.nextDep = next;
					link.prevDep = activeSub.depsTail;
					link.nextDep = void 0;
					activeSub.depsTail.nextDep = link;
					activeSub.depsTail = link;
					if (activeSub.deps === link) activeSub.deps = next;
				}
			}
			return link;
		}
		trigger(debugInfo) {
			this.version++;
			globalVersion++;
			this.notify(debugInfo);
		}
		notify(debugInfo) {
			startBatch();
			try {
				for (let link = this.subs; link; link = link.prevSub) if (link.sub.notify()) link.sub.dep.notify();
			} finally {
				endBatch();
			}
		}
	};
	function addSub(link) {
		link.dep.sc++;
		if (link.sub.flags & 4) {
			const computed = link.dep.computed;
			if (computed && !link.dep.subs) {
				computed.flags |= 20;
				for (let l = computed.deps; l; l = l.nextDep) addSub(l);
			}
			const currentTail = link.dep.subs;
			if (currentTail !== link) {
				link.prevSub = currentTail;
				if (currentTail) currentTail.nextSub = link;
			}
			link.dep.subs = link;
		}
	}
	var targetMap = /* @__PURE__ */ new WeakMap();
	var ITERATE_KEY = /* @__PURE__ */ Symbol("");
	var MAP_KEY_ITERATE_KEY = /* @__PURE__ */ Symbol("");
	var ARRAY_ITERATE_KEY = /* @__PURE__ */ Symbol("");
	function track(target, type, key) {
		if (shouldTrack && activeSub) {
			let depsMap = targetMap.get(target);
			if (!depsMap) targetMap.set(target, depsMap = /* @__PURE__ */ new Map());
			let dep = depsMap.get(key);
			if (!dep) {
				depsMap.set(key, dep = new Dep());
				dep.map = depsMap;
				dep.key = key;
			}
			dep.track();
		}
	}
	function trigger(target, type, key, newValue, oldValue, oldTarget) {
		const depsMap = targetMap.get(target);
		if (!depsMap) {
			globalVersion++;
			return;
		}
		const run = (dep) => {
			if (dep) dep.trigger();
		};
		startBatch();
		if (type === "clear") depsMap.forEach(run);
		else {
			const targetIsArray = isArray$1(target);
			const isArrayIndex = targetIsArray && isIntegerKey(key);
			if (targetIsArray && key === "length") {
				const newLength = Number(newValue);
				depsMap.forEach((dep, key2) => {
					if (key2 === "length" || key2 === ARRAY_ITERATE_KEY || !isSymbol(key2) && key2 >= newLength) run(dep);
				});
			} else {
				if (key !== void 0 || depsMap.has(void 0)) run(depsMap.get(key));
				if (isArrayIndex) run(depsMap.get(ARRAY_ITERATE_KEY));
				switch (type) {
					case "add":
						if (!targetIsArray) {
							run(depsMap.get(ITERATE_KEY));
							if (isMap(target)) run(depsMap.get(MAP_KEY_ITERATE_KEY));
						} else if (isArrayIndex) run(depsMap.get("length"));
						break;
					case "delete":
						if (!targetIsArray) {
							run(depsMap.get(ITERATE_KEY));
							if (isMap(target)) run(depsMap.get(MAP_KEY_ITERATE_KEY));
						}
						break;
					case "set": if (isMap(target)) run(depsMap.get(ITERATE_KEY));
				}
			}
		}
		endBatch();
	}
	function getDepFromReactive(object, key) {
		const depMap = targetMap.get(object);
		return depMap && depMap.get(key);
	}
	function reactiveReadArray(array) {
		const raw = /* @__PURE__ */ toRaw(array);
		if (raw === array) return raw;
		track(raw, "iterate", ARRAY_ITERATE_KEY);
		return /* @__PURE__ */ isShallow(array) ? raw : raw.map(toReactive);
	}
	function shallowReadArray(arr) {
		track(arr = /* @__PURE__ */ toRaw(arr), "iterate", ARRAY_ITERATE_KEY);
		return arr;
	}
	function toWrapped(target, item) {
		if (/* @__PURE__ */ isReadonly(target)) return /* @__PURE__ */ isReactive(target) ? toReadonly(toReactive(item)) : toReadonly(item);
		return toReactive(item);
	}
	var arrayInstrumentations = {
		__proto__: null,
		[Symbol.iterator]() {
			return iterator(this, Symbol.iterator, (item) => toWrapped(this, item));
		},
		concat(...args) {
			return reactiveReadArray(this).concat(...args.map((x) => isArray$1(x) ? reactiveReadArray(x) : x));
		},
		entries() {
			return iterator(this, "entries", (value) => {
				value[1] = toWrapped(this, value[1]);
				return value;
			});
		},
		every(fn, thisArg) {
			return apply(this, "every", fn, thisArg, void 0, arguments);
		},
		filter(fn, thisArg) {
			return apply(this, "filter", fn, thisArg, (v) => v.map((item) => toWrapped(this, item)), arguments);
		},
		find(fn, thisArg) {
			return apply(this, "find", fn, thisArg, (item) => toWrapped(this, item), arguments);
		},
		findIndex(fn, thisArg) {
			return apply(this, "findIndex", fn, thisArg, void 0, arguments);
		},
		findLast(fn, thisArg) {
			return apply(this, "findLast", fn, thisArg, (item) => toWrapped(this, item), arguments);
		},
		findLastIndex(fn, thisArg) {
			return apply(this, "findLastIndex", fn, thisArg, void 0, arguments);
		},
		forEach(fn, thisArg) {
			return apply(this, "forEach", fn, thisArg, void 0, arguments);
		},
		includes(...args) {
			return searchProxy(this, "includes", args);
		},
		indexOf(...args) {
			return searchProxy(this, "indexOf", args);
		},
		join(separator) {
			return reactiveReadArray(this).join(separator);
		},
		lastIndexOf(...args) {
			return searchProxy(this, "lastIndexOf", args);
		},
		map(fn, thisArg) {
			return apply(this, "map", fn, thisArg, void 0, arguments);
		},
		pop() {
			return noTracking(this, "pop");
		},
		push(...args) {
			return noTracking(this, "push", args);
		},
		reduce(fn, ...args) {
			return reduce(this, "reduce", fn, args);
		},
		reduceRight(fn, ...args) {
			return reduce(this, "reduceRight", fn, args);
		},
		shift() {
			return noTracking(this, "shift");
		},
		some(fn, thisArg) {
			return apply(this, "some", fn, thisArg, void 0, arguments);
		},
		splice(...args) {
			return noTracking(this, "splice", args);
		},
		toReversed() {
			return reactiveReadArray(this).toReversed();
		},
		toSorted(comparer) {
			return reactiveReadArray(this).toSorted(comparer);
		},
		toSpliced(...args) {
			return reactiveReadArray(this).toSpliced(...args);
		},
		unshift(...args) {
			return noTracking(this, "unshift", args);
		},
		values() {
			return iterator(this, "values", (item) => toWrapped(this, item));
		}
	};
	function iterator(self, method, wrapValue) {
		const arr = shallowReadArray(self);
		const iter = arr[method]();
		if (arr !== self && !/* @__PURE__ */ isShallow(self)) {
			iter._next = iter.next;
			iter.next = () => {
				const result = iter._next();
				if (!result.done) result.value = wrapValue(result.value);
				return result;
			};
		}
		return iter;
	}
	var arrayProto = Array.prototype;
	function apply(self, method, fn, thisArg, wrappedRetFn, args) {
		const arr = shallowReadArray(self);
		const needsWrap = arr !== self && !/* @__PURE__ */ isShallow(self);
		const methodFn = arr[method];
		if (methodFn !== arrayProto[method]) {
			const result2 = methodFn.apply(self, args);
			return needsWrap ? toReactive(result2) : result2;
		}
		let wrappedFn = fn;
		if (arr !== self) {
			if (needsWrap) wrappedFn = function(item, index) {
				return fn.call(this, toWrapped(self, item), index, self);
			};
			else if (fn.length > 2) wrappedFn = function(item, index) {
				return fn.call(this, item, index, self);
			};
		}
		const result = methodFn.call(arr, wrappedFn, thisArg);
		return needsWrap && wrappedRetFn ? wrappedRetFn(result) : result;
	}
	function reduce(self, method, fn, args) {
		const arr = shallowReadArray(self);
		const needsWrap = arr !== self && !/* @__PURE__ */ isShallow(self);
		let wrappedFn = fn;
		let wrapInitialAccumulator = false;
		if (arr !== self) {
			if (needsWrap) {
				wrapInitialAccumulator = args.length === 0;
				wrappedFn = function(acc, item, index) {
					if (wrapInitialAccumulator) {
						wrapInitialAccumulator = false;
						acc = toWrapped(self, acc);
					}
					return fn.call(this, acc, toWrapped(self, item), index, self);
				};
			} else if (fn.length > 3) wrappedFn = function(acc, item, index) {
				return fn.call(this, acc, item, index, self);
			};
		}
		const result = arr[method](wrappedFn, ...args);
		return wrapInitialAccumulator ? toWrapped(self, result) : result;
	}
	function searchProxy(self, method, args) {
		const arr = /* @__PURE__ */ toRaw(self);
		track(arr, "iterate", ARRAY_ITERATE_KEY);
		const res = arr[method](...args);
		if ((res === -1 || res === false) && /* @__PURE__ */ isProxy(args[0])) {
			args[0] = /* @__PURE__ */ toRaw(args[0]);
			return arr[method](...args);
		}
		return res;
	}
	function noTracking(self, method, args = []) {
		pauseTracking();
		startBatch();
		const res = (/* @__PURE__ */ toRaw(self))[method].apply(self, args);
		endBatch();
		resetTracking();
		return res;
	}
	var isNonTrackableKeys = /* @__PURE__ */ makeMap(`__proto__,__v_isRef,__isVue`);
	var builtInSymbols = new Set(/* @__PURE__ */ Object.getOwnPropertyNames(Symbol).filter((key) => key !== "arguments" && key !== "caller").map((key) => Symbol[key]).filter(isSymbol));
	function hasOwnProperty(key) {
		if (!isSymbol(key)) key = String(key);
		const obj = /* @__PURE__ */ toRaw(this);
		track(obj, "has", key);
		return obj.hasOwnProperty(key);
	}
	var BaseReactiveHandler = class {
		constructor(_isReadonly = false, _isShallow = false) {
			this._isReadonly = _isReadonly;
			this._isShallow = _isShallow;
		}
		get(target, key, receiver) {
			if (key === "__v_skip") return target["__v_skip"];
			const isReadonly2 = this._isReadonly, isShallow2 = this._isShallow;
			if (key === "__v_isReactive") return !isReadonly2;
			else if (key === "__v_isReadonly") return isReadonly2;
			else if (key === "__v_isShallow") return isShallow2;
			else if (key === "__v_raw") {
				if (receiver === (isReadonly2 ? isShallow2 ? shallowReadonlyMap : readonlyMap : isShallow2 ? shallowReactiveMap : reactiveMap).get(target) || Object.getPrototypeOf(target) === Object.getPrototypeOf(receiver)) return target;
				return;
			}
			const targetIsArray = isArray$1(target);
			if (!isReadonly2) {
				let fn;
				if (targetIsArray && (fn = arrayInstrumentations[key])) return fn;
				if (key === "hasOwnProperty") return hasOwnProperty;
			}
			const res = Reflect.get(target, key, /* @__PURE__ */ isRef(target) ? target : receiver);
			if (isSymbol(key) ? builtInSymbols.has(key) : isNonTrackableKeys(key)) return res;
			if (!isReadonly2) track(target, "get", key);
			if (isShallow2) return res;
			if (/* @__PURE__ */ isRef(res)) {
				const value = targetIsArray && isIntegerKey(key) ? res : res.value;
				return isReadonly2 && isObject(value) ? /* @__PURE__ */ readonly(value) : value;
			}
			if (isObject(res)) return isReadonly2 ? /* @__PURE__ */ readonly(res) : /* @__PURE__ */ reactive(res);
			return res;
		}
	};
	var MutableReactiveHandler = class extends BaseReactiveHandler {
		constructor(isShallow2 = false) {
			super(false, isShallow2);
		}
		set(target, key, value, receiver) {
			let oldValue = target[key];
			const isArrayWithIntegerKey = isArray$1(target) && isIntegerKey(key);
			if (!this._isShallow) {
				const isOldValueReadonly = /* @__PURE__ */ isReadonly(oldValue);
				if (!/* @__PURE__ */ isShallow(value) && !/* @__PURE__ */ isReadonly(value)) {
					oldValue = /* @__PURE__ */ toRaw(oldValue);
					value = /* @__PURE__ */ toRaw(value);
				}
				if (!isArrayWithIntegerKey && /* @__PURE__ */ isRef(oldValue) && !/* @__PURE__ */ isRef(value)) {
					if (isOldValueReadonly) return true;
					else {
						oldValue.value = value;
						return true;
					}
				}
			}
			const hadKey = isArrayWithIntegerKey ? Number(key) < target.length : hasOwn(target, key);
			const result = Reflect.set(target, key, value, /* @__PURE__ */ isRef(target) ? target : receiver);
			if (target === /* @__PURE__ */ toRaw(receiver) && result) {
				if (!hadKey) trigger(target, "add", key, value);
				else if (hasChanged(value, oldValue)) trigger(target, "set", key, value, oldValue);
			}
			return result;
		}
		deleteProperty(target, key) {
			const hadKey = hasOwn(target, key);
			const oldValue = target[key];
			const result = Reflect.deleteProperty(target, key);
			if (result && hadKey) trigger(target, "delete", key, void 0, oldValue);
			return result;
		}
		has(target, key) {
			const result = Reflect.has(target, key);
			if (!isSymbol(key) || !builtInSymbols.has(key)) track(target, "has", key);
			return result;
		}
		ownKeys(target) {
			track(target, "iterate", isArray$1(target) ? "length" : ITERATE_KEY);
			return Reflect.ownKeys(target);
		}
	};
	var ReadonlyReactiveHandler = class extends BaseReactiveHandler {
		constructor(isShallow2 = false) {
			super(true, isShallow2);
		}
		set(target, key) {
			return true;
		}
		deleteProperty(target, key) {
			return true;
		}
	};
	var mutableHandlers = /* @__PURE__ */ new MutableReactiveHandler();
	var readonlyHandlers = /* @__PURE__ */ new ReadonlyReactiveHandler();
	var shallowReactiveHandlers = /* @__PURE__ */ new MutableReactiveHandler(true);
	var shallowReadonlyHandlers = /* @__PURE__ */ new ReadonlyReactiveHandler(true);
	var toShallow = (value) => value;
	var getProto = (v) => Reflect.getPrototypeOf(v);
	function createIterableMethod(method, isReadonly2, isShallow2) {
		return function(...args) {
			const target = this["__v_raw"];
			const rawTarget = /* @__PURE__ */ toRaw(target);
			const targetIsMap = isMap(rawTarget);
			const isPair = method === "entries" || method === Symbol.iterator && targetIsMap;
			const isKeyOnly = method === "keys" && targetIsMap;
			const innerIterator = target[method](...args);
			const wrap = isShallow2 ? toShallow : isReadonly2 ? toReadonly : toReactive;
			!isReadonly2 && track(rawTarget, "iterate", isKeyOnly ? MAP_KEY_ITERATE_KEY : ITERATE_KEY);
			return extend(Object.create(innerIterator), { next() {
				const { value, done } = innerIterator.next();
				return done ? {
					value,
					done
				} : {
					value: isPair ? [wrap(value[0]), wrap(value[1])] : wrap(value),
					done
				};
			} });
		};
	}
	function createReadonlyMethod(type) {
		return function(...args) {
			return type === "delete" ? false : type === "clear" ? void 0 : this;
		};
	}
	function createInstrumentations(readonly, shallow) {
		const instrumentations = {
			get(key) {
				const target = this["__v_raw"];
				const rawTarget = /* @__PURE__ */ toRaw(target);
				const rawKey = /* @__PURE__ */ toRaw(key);
				if (!readonly) {
					if (hasChanged(key, rawKey)) track(rawTarget, "get", key);
					track(rawTarget, "get", rawKey);
				}
				const { has } = getProto(rawTarget);
				const wrap = shallow ? toShallow : readonly ? toReadonly : toReactive;
				if (has.call(rawTarget, key)) return wrap(target.get(key));
				else if (has.call(rawTarget, rawKey)) return wrap(target.get(rawKey));
				else if (target !== rawTarget) target.get(key);
			},
			get size() {
				const target = this["__v_raw"];
				!readonly && track(/* @__PURE__ */ toRaw(target), "iterate", ITERATE_KEY);
				return target.size;
			},
			has(key) {
				const target = this["__v_raw"];
				const rawTarget = /* @__PURE__ */ toRaw(target);
				const rawKey = /* @__PURE__ */ toRaw(key);
				if (!readonly) {
					if (hasChanged(key, rawKey)) track(rawTarget, "has", key);
					track(rawTarget, "has", rawKey);
				}
				return key === rawKey ? target.has(key) : target.has(key) || target.has(rawKey);
			},
			forEach(callback, thisArg) {
				const observed = this;
				const target = observed["__v_raw"];
				const rawTarget = /* @__PURE__ */ toRaw(target);
				const wrap = shallow ? toShallow : readonly ? toReadonly : toReactive;
				!readonly && track(rawTarget, "iterate", ITERATE_KEY);
				return target.forEach((value, key) => {
					return callback.call(thisArg, wrap(value), wrap(key), observed);
				});
			}
		};
		extend(instrumentations, readonly ? {
			add: createReadonlyMethod("add"),
			set: createReadonlyMethod("set"),
			delete: createReadonlyMethod("delete"),
			clear: createReadonlyMethod("clear")
		} : {
			add(value) {
				const target = /* @__PURE__ */ toRaw(this);
				const proto = getProto(target);
				const rawValue = /* @__PURE__ */ toRaw(value);
				const valueToAdd = !shallow && !/* @__PURE__ */ isShallow(value) && !/* @__PURE__ */ isReadonly(value) ? rawValue : value;
				if (!(proto.has.call(target, valueToAdd) || hasChanged(value, valueToAdd) && proto.has.call(target, value) || hasChanged(rawValue, valueToAdd) && proto.has.call(target, rawValue))) {
					target.add(valueToAdd);
					trigger(target, "add", valueToAdd, valueToAdd);
				}
				return this;
			},
			set(key, value) {
				if (!shallow && !/* @__PURE__ */ isShallow(value) && !/* @__PURE__ */ isReadonly(value)) value = /* @__PURE__ */ toRaw(value);
				const target = /* @__PURE__ */ toRaw(this);
				const { has, get } = getProto(target);
				let hadKey = has.call(target, key);
				if (!hadKey) {
					key = /* @__PURE__ */ toRaw(key);
					hadKey = has.call(target, key);
				}
				const oldValue = get.call(target, key);
				target.set(key, value);
				if (!hadKey) trigger(target, "add", key, value);
				else if (hasChanged(value, oldValue)) trigger(target, "set", key, value, oldValue);
				return this;
			},
			delete(key) {
				const target = /* @__PURE__ */ toRaw(this);
				const { has, get } = getProto(target);
				let hadKey = has.call(target, key);
				if (!hadKey) {
					key = /* @__PURE__ */ toRaw(key);
					hadKey = has.call(target, key);
				}
				const oldValue = get ? get.call(target, key) : void 0;
				const result = target.delete(key);
				if (hadKey) trigger(target, "delete", key, void 0, oldValue);
				return result;
			},
			clear() {
				const target = /* @__PURE__ */ toRaw(this);
				const hadItems = target.size !== 0;
				const oldTarget = void 0;
				const result = target.clear();
				if (hadItems) trigger(target, "clear", void 0, void 0, oldTarget);
				return result;
			}
		});
		[
			"keys",
			"values",
			"entries",
			Symbol.iterator
		].forEach((method) => {
			instrumentations[method] = createIterableMethod(method, readonly, shallow);
		});
		return instrumentations;
	}
	function createInstrumentationGetter(isReadonly2, shallow) {
		const instrumentations = createInstrumentations(isReadonly2, shallow);
		return (target, key, receiver) => {
			if (key === "__v_isReactive") return !isReadonly2;
			else if (key === "__v_isReadonly") return isReadonly2;
			else if (key === "__v_raw") return target;
			return Reflect.get(hasOwn(instrumentations, key) && key in target ? instrumentations : target, key, receiver);
		};
	}
	var mutableCollectionHandlers = { get: /* @__PURE__ */ createInstrumentationGetter(false, false) };
	var shallowCollectionHandlers = { get: /* @__PURE__ */ createInstrumentationGetter(false, true) };
	var readonlyCollectionHandlers = { get: /* @__PURE__ */ createInstrumentationGetter(true, false) };
	var shallowReadonlyCollectionHandlers = { get: /* @__PURE__ */ createInstrumentationGetter(true, true) };
	var reactiveMap = /* @__PURE__ */ new WeakMap();
	var shallowReactiveMap = /* @__PURE__ */ new WeakMap();
	var readonlyMap = /* @__PURE__ */ new WeakMap();
	var shallowReadonlyMap = /* @__PURE__ */ new WeakMap();
	function targetTypeMap(rawType) {
		switch (rawType) {
			case "Object":
			case "Array": return 1;
			case "Map":
			case "Set":
			case "WeakMap":
			case "WeakSet": return 2;
			default: return 0;
		}
	}
	// @__NO_SIDE_EFFECTS__
	function reactive(target) {
		if (/* @__PURE__ */ isReadonly(target)) return target;
		return createReactiveObject(target, false, mutableHandlers, mutableCollectionHandlers, reactiveMap);
	}
	// @__NO_SIDE_EFFECTS__
	function shallowReactive(target) {
		return createReactiveObject(target, false, shallowReactiveHandlers, shallowCollectionHandlers, shallowReactiveMap);
	}
	// @__NO_SIDE_EFFECTS__
	function readonly(target) {
		return createReactiveObject(target, true, readonlyHandlers, readonlyCollectionHandlers, readonlyMap);
	}
	// @__NO_SIDE_EFFECTS__
	function shallowReadonly(target) {
		return createReactiveObject(target, true, shallowReadonlyHandlers, shallowReadonlyCollectionHandlers, shallowReadonlyMap);
	}
	function createReactiveObject(target, isReadonly2, baseHandlers, collectionHandlers, proxyMap) {
		if (!isObject(target)) return target;
		if (target["__v_raw"] && !(isReadonly2 && target["__v_isReactive"])) return target;
		if (target["__v_skip"] || !Object.isExtensible(target)) return target;
		const existingProxy = proxyMap.get(target);
		if (existingProxy) return existingProxy;
		const targetType = targetTypeMap(toRawType(target));
		if (targetType === 0) return target;
		const proxy = new Proxy(target, targetType === 2 ? collectionHandlers : baseHandlers);
		proxyMap.set(target, proxy);
		return proxy;
	}
	// @__NO_SIDE_EFFECTS__
	function isReactive(value) {
		if (/* @__PURE__ */ isReadonly(value)) return /* @__PURE__ */ isReactive(value["__v_raw"]);
		return !!(value && value["__v_isReactive"]);
	}
	// @__NO_SIDE_EFFECTS__
	function isReadonly(value) {
		return !!(value && value["__v_isReadonly"]);
	}
	// @__NO_SIDE_EFFECTS__
	function isShallow(value) {
		return !!(value && value["__v_isShallow"]);
	}
	// @__NO_SIDE_EFFECTS__
	function isProxy(value) {
		return value ? !!value["__v_raw"] : false;
	}
	// @__NO_SIDE_EFFECTS__
	function toRaw(observed) {
		const raw = observed && observed["__v_raw"];
		return raw ? /* @__PURE__ */ toRaw(raw) : observed;
	}
	function markRaw(value) {
		if (!hasOwn(value, "__v_skip") && Object.isExtensible(value)) def(value, "__v_skip", true);
		return value;
	}
	var toReactive = (value) => isObject(value) ? /* @__PURE__ */ reactive(value) : value;
	var toReadonly = (value) => isObject(value) ? /* @__PURE__ */ readonly(value) : value;
	// @__NO_SIDE_EFFECTS__
	function isRef(r) {
		return r ? r["__v_isRef"] === true : false;
	}
	// @__NO_SIDE_EFFECTS__
	function ref(value) {
		return createRef(value, false);
	}
	// @__NO_SIDE_EFFECTS__
	function shallowRef(value) {
		return createRef(value, true);
	}
	function createRef(rawValue, shallow) {
		if (/* @__PURE__ */ isRef(rawValue)) return rawValue;
		return new RefImpl(rawValue, shallow);
	}
	var RefImpl = class {
		constructor(value, isShallow2) {
			this.dep = new Dep();
			this["__v_isRef"] = true;
			this["__v_isShallow"] = false;
			this._rawValue = isShallow2 ? value : /* @__PURE__ */ toRaw(value);
			this._value = isShallow2 ? value : toReactive(value);
			this["__v_isShallow"] = isShallow2;
		}
		get value() {
			this.dep.track();
			return this._value;
		}
		set value(newValue) {
			const oldValue = this._rawValue;
			const useDirectValue = this["__v_isShallow"] || /* @__PURE__ */ isShallow(newValue) || /* @__PURE__ */ isReadonly(newValue);
			newValue = useDirectValue ? newValue : /* @__PURE__ */ toRaw(newValue);
			if (hasChanged(newValue, oldValue)) {
				this._rawValue = newValue;
				this._value = useDirectValue ? newValue : toReactive(newValue);
				this.dep.trigger();
			}
		}
	};
	function unref(ref2) {
		return /* @__PURE__ */ isRef(ref2) ? ref2.value : ref2;
	}
	var shallowUnwrapHandlers = {
		get: (target, key, receiver) => key === "__v_raw" ? target : unref(Reflect.get(target, key, receiver)),
		set: (target, key, value, receiver) => {
			const oldValue = target[key];
			if (/* @__PURE__ */ isRef(oldValue) && !/* @__PURE__ */ isRef(value)) {
				oldValue.value = value;
				return true;
			} else return Reflect.set(target, key, value, receiver);
		}
	};
	function proxyRefs(objectWithRefs) {
		return /* @__PURE__ */ isReactive(objectWithRefs) ? objectWithRefs : new Proxy(objectWithRefs, shallowUnwrapHandlers);
	}
	// @__NO_SIDE_EFFECTS__
	function toRefs(object) {
		const ret = isArray$1(object) ? new Array(object.length) : {};
		for (const key in object) ret[key] = propertyToRef(object, key);
		return ret;
	}
	var ObjectRefImpl = class {
		constructor(_object, key, _defaultValue) {
			this._object = _object;
			this._defaultValue = _defaultValue;
			this["__v_isRef"] = true;
			this._value = void 0;
			this._key = isSymbol(key) ? key : String(key);
			this._raw = /* @__PURE__ */ toRaw(_object);
			let shallow = true;
			let obj = _object;
			if (!isArray$1(_object) || isSymbol(this._key) || !isIntegerKey(this._key)) do
				shallow = !/* @__PURE__ */ isProxy(obj) || /* @__PURE__ */ isShallow(obj);
			while (shallow && (obj = obj["__v_raw"]));
			this._shallow = shallow;
		}
		get value() {
			let val = this._object[this._key];
			if (this._shallow) val = unref(val);
			return this._value = val === void 0 ? this._defaultValue : val;
		}
		set value(newVal) {
			if (this._shallow && /* @__PURE__ */ isRef(this._raw[this._key])) {
				const nestedRef = this._object[this._key];
				if (/* @__PURE__ */ isRef(nestedRef)) {
					nestedRef.value = newVal;
					return;
				}
			}
			this._object[this._key] = newVal;
		}
		get dep() {
			return getDepFromReactive(this._raw, this._key);
		}
	};
	function propertyToRef(source, key, defaultValue) {
		return new ObjectRefImpl(source, key, defaultValue);
	}
	var ComputedRefImpl = class {
		constructor(fn, setter, isSSR) {
			this.fn = fn;
			this.setter = setter;
			/**
			* @internal
			*/
			this._value = void 0;
			/**
			* @internal
			*/
			this.dep = new Dep(this);
			/**
			* @internal
			*/
			this.__v_isRef = true;
			/**
			* @internal
			*/
			this.deps = void 0;
			/**
			* @internal
			*/
			this.depsTail = void 0;
			/**
			* @internal
			*/
			this.flags = 16;
			/**
			* @internal
			*/
			this.globalVersion = globalVersion - 1;
			/**
			* @internal
			*/
			this.next = void 0;
			this.effect = this;
			this["__v_isReadonly"] = !setter;
			this.isSSR = isSSR;
		}
		/**
		* @internal
		*/
		notify() {
			this.flags |= 16;
			if (!(this.flags & 8) && activeSub !== this) {
				batch(this, true);
				return true;
			}
		}
		get value() {
			const link = this.dep.track();
			refreshComputed(this);
			if (link) link.version = this.dep.version;
			return this._value;
		}
		set value(newValue) {
			if (this.setter) this.setter(newValue);
		}
	};
	// @__NO_SIDE_EFFECTS__
	function computed$1(getterOrOptions, debugOptions, isSSR = false) {
		let getter;
		let setter;
		if (isFunction$1(getterOrOptions)) getter = getterOrOptions;
		else {
			getter = getterOrOptions.get;
			setter = getterOrOptions.set;
		}
		return new ComputedRefImpl(getter, setter, isSSR);
	}
	var INITIAL_WATCHER_VALUE = {};
	var cleanupMap = /* @__PURE__ */ new WeakMap();
	var activeWatcher = void 0;
	function onWatcherCleanup(cleanupFn, failSilently = false, owner = activeWatcher) {
		if (owner) {
			let cleanups = cleanupMap.get(owner);
			if (!cleanups) cleanupMap.set(owner, cleanups = []);
			cleanups.push(cleanupFn);
		}
	}
	function watch$1(source, cb, options = EMPTY_OBJ) {
		const { immediate, deep, once, scheduler, augmentJob, call } = options;
		const reactiveGetter = (source2) => {
			if (deep) return source2;
			if (/* @__PURE__ */ isShallow(source2) || deep === false || deep === 0) return traverse(source2, 1);
			return traverse(source2);
		};
		let effect;
		let getter;
		let cleanup;
		let boundCleanup;
		let forceTrigger = false;
		let isMultiSource = false;
		if (/* @__PURE__ */ isRef(source)) {
			getter = () => source.value;
			forceTrigger = /* @__PURE__ */ isShallow(source);
		} else if (/* @__PURE__ */ isReactive(source)) {
			getter = () => reactiveGetter(source);
			forceTrigger = true;
		} else if (isArray$1(source)) {
			isMultiSource = true;
			forceTrigger = source.some((s) => /* @__PURE__ */ isReactive(s) || /* @__PURE__ */ isShallow(s));
			getter = () => source.map((s) => {
				if (/* @__PURE__ */ isRef(s)) return s.value;
				else if (/* @__PURE__ */ isReactive(s)) return reactiveGetter(s);
				else if (isFunction$1(s)) return call ? call(s, 2) : s();
			});
		} else if (isFunction$1(source)) {
			if (cb) getter = call ? () => call(source, 2) : source;
			else getter = () => {
				if (cleanup) {
					pauseTracking();
					try {
						cleanup();
					} finally {
						resetTracking();
					}
				}
				const currentEffect = activeWatcher;
				activeWatcher = effect;
				try {
					return call ? call(source, 3, [boundCleanup]) : source(boundCleanup);
				} finally {
					activeWatcher = currentEffect;
				}
			};
		} else getter = NOOP;
		if (cb && deep) {
			const baseGetter = getter;
			const depth = deep === true ? Infinity : deep;
			getter = () => traverse(baseGetter(), depth);
		}
		const scope = getCurrentScope();
		const watchHandle = () => {
			effect.stop();
			if (scope && scope.active) remove(scope.effects, effect);
		};
		if (once && cb) {
			const _cb = cb;
			cb = (...args) => {
				const res = _cb(...args);
				watchHandle();
				return res;
			};
		}
		let oldValue = isMultiSource ? new Array(source.length).fill(INITIAL_WATCHER_VALUE) : INITIAL_WATCHER_VALUE;
		const job = (immediateFirstRun) => {
			if (!(effect.flags & 1) || !effect.dirty && !immediateFirstRun) return;
			if (cb) {
				const newValue = effect.run();
				if (immediateFirstRun || deep || forceTrigger || (isMultiSource ? newValue.some((v, i) => hasChanged(v, oldValue[i])) : hasChanged(newValue, oldValue))) {
					if (cleanup) cleanup();
					const currentWatcher = activeWatcher;
					activeWatcher = effect;
					try {
						const args = [
							newValue,
							oldValue === INITIAL_WATCHER_VALUE ? void 0 : isMultiSource && oldValue[0] === INITIAL_WATCHER_VALUE ? [] : oldValue,
							boundCleanup
						];
						oldValue = newValue;
						call ? call(cb, 3, args) : cb(...args);
					} finally {
						activeWatcher = currentWatcher;
					}
				}
			} else effect.run();
		};
		if (augmentJob) augmentJob(job);
		effect = new ReactiveEffect(getter);
		effect.scheduler = scheduler ? () => scheduler(job, false) : job;
		boundCleanup = (fn) => onWatcherCleanup(fn, false, effect);
		cleanup = effect.onStop = () => {
			const cleanups = cleanupMap.get(effect);
			if (cleanups) {
				if (call) call(cleanups, 4);
				else for (const cleanup2 of cleanups) cleanup2();
				cleanupMap.delete(effect);
			}
		};
		if (cb) {
			if (immediate) job(true);
			else oldValue = effect.run();
		} else if (scheduler) scheduler(job.bind(null, true), true);
		else effect.run();
		watchHandle.pause = effect.pause.bind(effect);
		watchHandle.resume = effect.resume.bind(effect);
		watchHandle.stop = watchHandle;
		return watchHandle;
	}
	function traverse(value, depth = Infinity, seen) {
		if (depth <= 0 || !isObject(value) || value["__v_skip"]) return value;
		seen = seen || /* @__PURE__ */ new Map();
		if ((seen.get(value) || 0) >= depth) return value;
		seen.set(value, depth);
		depth--;
		if (/* @__PURE__ */ isRef(value)) traverse(value.value, depth, seen);
		else if (isArray$1(value)) for (let i = 0; i < value.length; i++) traverse(value[i], depth, seen);
		else if (isSet(value) || isMap(value)) value.forEach((v) => {
			traverse(v, depth, seen);
		});
		else if (isPlainObject$2(value)) {
			for (const key in value) traverse(value[key], depth, seen);
			for (const key of Object.getOwnPropertySymbols(value)) if (Object.prototype.propertyIsEnumerable.call(value, key)) traverse(value[key], depth, seen);
		}
		return value;
	}
	//#endregion
	//#region node_modules/@vue/runtime-core/dist/runtime-core.esm-bundler.js
	/**
	* @vue/runtime-core v3.5.41
	* (c) 2018-present Yuxi (Evan) You and Vue contributors
	* @license MIT
	**/
	function callWithErrorHandling(fn, instance, type, args) {
		try {
			return args ? fn(...args) : fn();
		} catch (err) {
			handleError(err, instance, type);
		}
	}
	function callWithAsyncErrorHandling(fn, instance, type, args) {
		if (isFunction$1(fn)) {
			const res = callWithErrorHandling(fn, instance, type, args);
			if (res && isPromise(res)) res.catch((err) => {
				handleError(err, instance, type);
			});
			return res;
		}
		if (isArray$1(fn)) {
			const values = [];
			for (let i = 0; i < fn.length; i++) values.push(callWithAsyncErrorHandling(fn[i], instance, type, args));
			return values;
		}
	}
	function handleError(err, instance, type, throwInDev = true) {
		const contextVNode = instance ? instance.vnode : null;
		const { errorHandler, throwUnhandledErrorInProduction } = instance && instance.appContext.config || EMPTY_OBJ;
		if (instance) {
			let cur = instance.parent;
			const exposedInstance = instance.proxy;
			const errorInfo = `https://vuejs.org/error-reference/#runtime-${type}`;
			while (cur) {
				const errorCapturedHooks = cur.ec;
				if (errorCapturedHooks) {
					for (let i = 0; i < errorCapturedHooks.length; i++) if (errorCapturedHooks[i](err, exposedInstance, errorInfo) === false) return;
				}
				cur = cur.parent;
			}
			if (errorHandler) {
				pauseTracking();
				callWithErrorHandling(errorHandler, null, 10, [
					err,
					exposedInstance,
					errorInfo
				]);
				resetTracking();
				return;
			}
		}
		logError(err, type, contextVNode, throwInDev, throwUnhandledErrorInProduction);
	}
	function logError(err, type, contextVNode, throwInDev = true, throwInProd = false) {
		if (throwInProd) throw err;
		else console.error(err);
	}
	var queue = [];
	var flushIndex = -1;
	var pendingPostFlushCbs = [];
	var activePostFlushCbs = null;
	var postFlushIndex = 0;
	var resolvedPromise = /* @__PURE__ */ Promise.resolve();
	var currentFlushPromise = null;
	function nextTick(fn) {
		const p = currentFlushPromise || resolvedPromise;
		return fn ? p.then(this ? fn.bind(this) : fn) : p;
	}
	function findInsertionIndex$1(id) {
		let start = flushIndex + 1;
		let end = queue.length;
		while (start < end) {
			const middle = start + end >>> 1;
			const middleJob = queue[middle];
			const middleJobId = getId(middleJob);
			if (middleJobId < id || middleJobId === id && middleJob.flags & 2) start = middle + 1;
			else end = middle;
		}
		return start;
	}
	function queueJob(job) {
		if (!(job.flags & 1)) {
			const jobId = getId(job);
			const lastJob = queue[queue.length - 1];
			if (!lastJob || !(job.flags & 2) && jobId >= getId(lastJob)) queue.push(job);
			else queue.splice(findInsertionIndex$1(jobId), 0, job);
			job.flags |= 1;
			queueFlush();
		}
	}
	function queueFlush() {
		if (!currentFlushPromise) currentFlushPromise = resolvedPromise.then(flushJobs);
	}
	function queuePostFlushCb(cb) {
		if (!isArray$1(cb)) {
			if (activePostFlushCbs && cb.id === -1) activePostFlushCbs.splice(postFlushIndex + 1, 0, cb);
			else if (!(cb.flags & 1)) {
				pendingPostFlushCbs.push(cb);
				cb.flags |= 1;
			}
		} else for (let i = 0; i < cb.length; i++) pendingPostFlushCbs.push(cb[i]);
		queueFlush();
	}
	function flushPreFlushCbs(instance, seen, i = flushIndex + 1) {
		for (; i < queue.length; i++) {
			const cb = queue[i];
			if (cb && cb.flags & 2) {
				if (instance && cb.id !== instance.uid) continue;
				queue.splice(i, 1);
				i--;
				if (cb.flags & 4) cb.flags &= -2;
				cb();
				if (!(cb.flags & 4)) cb.flags &= -2;
			}
		}
	}
	function flushPostFlushCbs(seen) {
		if (pendingPostFlushCbs.length) {
			const deduped = [...new Set(pendingPostFlushCbs)].sort((a, b) => getId(a) - getId(b));
			pendingPostFlushCbs.length = 0;
			if (activePostFlushCbs) {
				for (let i = 0; i < deduped.length; i++) activePostFlushCbs.push(deduped[i]);
				return;
			}
			activePostFlushCbs = deduped;
			for (postFlushIndex = 0; postFlushIndex < activePostFlushCbs.length; postFlushIndex++) {
				const cb = activePostFlushCbs[postFlushIndex];
				if (cb.flags & 4) cb.flags &= -2;
				if (!(cb.flags & 8)) cb();
				cb.flags &= -2;
			}
			activePostFlushCbs = null;
			postFlushIndex = 0;
		}
	}
	var getId = (job) => job.id == null ? job.flags & 2 ? -1 : Infinity : job.id;
	function flushJobs(seen) {
		try {
			for (flushIndex = 0; flushIndex < queue.length; flushIndex++) {
				const job = queue[flushIndex];
				if (job && !(job.flags & 8)) {
					if (job.flags & 4) job.flags &= -2;
					callWithErrorHandling(job, job.i, job.i ? 15 : 14);
					if (!(job.flags & 4)) job.flags &= -2;
				}
			}
		} finally {
			for (; flushIndex < queue.length; flushIndex++) {
				const job = queue[flushIndex];
				if (job) job.flags &= -2;
			}
			flushIndex = -1;
			queue.length = 0;
			flushPostFlushCbs(seen);
			currentFlushPromise = null;
			if (queue.length || pendingPostFlushCbs.length) flushJobs(seen);
		}
	}
	var currentRenderingInstance = null;
	var currentScopeId = null;
	function setCurrentRenderingInstance(instance) {
		const prev = currentRenderingInstance;
		currentRenderingInstance = instance;
		currentScopeId = instance && instance.type.__scopeId || null;
		return prev;
	}
	function withCtx(fn, ctx = currentRenderingInstance, isNonScopedSlot) {
		if (!ctx) return fn;
		if (fn._n) return fn;
		const renderFnWithContext = (...args) => {
			if (renderFnWithContext._d) setBlockTracking(-1);
			const prevInstance = setCurrentRenderingInstance(ctx);
			const prevStackSize = blockStack.length;
			let res;
			try {
				res = fn(...args);
			} finally {
				for (let i = blockStack.length; i > prevStackSize; i--) closeBlock();
				setCurrentRenderingInstance(prevInstance);
				if (renderFnWithContext._d) setBlockTracking(1);
			}
			return res;
		};
		renderFnWithContext._n = true;
		renderFnWithContext._c = true;
		renderFnWithContext._d = true;
		return renderFnWithContext;
	}
	function withDirectives(vnode, directives) {
		if (currentRenderingInstance === null) return vnode;
		const instance = getComponentPublicInstance(currentRenderingInstance);
		const bindings = vnode.dirs || (vnode.dirs = []);
		for (let i = 0; i < directives.length; i++) {
			let [dir, value, arg, modifiers = EMPTY_OBJ] = directives[i];
			if (dir) {
				if (isFunction$1(dir)) dir = {
					mounted: dir,
					updated: dir
				};
				if (dir.deep) traverse(value);
				bindings.push({
					dir,
					instance,
					value,
					oldValue: void 0,
					arg,
					modifiers
				});
			}
		}
		return vnode;
	}
	function invokeDirectiveHook(vnode, prevVNode, instance, name) {
		const bindings = vnode.dirs;
		const oldBindings = prevVNode && prevVNode.dirs;
		for (let i = 0; i < bindings.length; i++) {
			const binding = bindings[i];
			if (oldBindings) binding.oldValue = oldBindings[i].value;
			let hook = binding.dir[name];
			if (hook) {
				pauseTracking();
				callWithAsyncErrorHandling(hook, instance, 8, [
					vnode.el,
					binding,
					vnode,
					prevVNode
				]);
				resetTracking();
			}
		}
	}
	function provide(key, value) {
		if (currentInstance) {
			let provides = currentInstance.provides;
			const parentProvides = currentInstance.parent && currentInstance.parent.provides;
			if (parentProvides === provides) provides = currentInstance.provides = Object.create(parentProvides);
			provides[key] = value;
		}
	}
	function inject(key, defaultValue, treatDefaultAsFactory = false) {
		const instance = getCurrentInstance();
		if (instance || currentApp) {
			let provides = currentApp ? currentApp._context.provides : instance ? instance.parent == null || instance.ce ? instance.vnode.appContext && instance.vnode.appContext.provides : instance.parent.provides : void 0;
			if (provides && key in provides) return provides[key];
			else if (arguments.length > 1) return treatDefaultAsFactory && isFunction$1(defaultValue) ? defaultValue.call(instance && instance.proxy) : defaultValue;
		}
	}
	function hasInjectionContext() {
		return !!(getCurrentInstance() || currentApp);
	}
	var ssrContextKey = /* @__PURE__ */ Symbol.for("v-scx");
	var useSSRContext = () => {
		{
			const ctx = inject(ssrContextKey);
			if (!ctx) {}
			return ctx;
		}
	};
	function watch(source, cb, options) {
		return doWatch(source, cb, options);
	}
	function doWatch(source, cb, options = EMPTY_OBJ) {
		const { immediate, deep, flush, once } = options;
		const baseWatchOptions = extend({}, options);
		const runsImmediately = cb && immediate || !cb && flush !== "post";
		let ssrCleanup;
		if (isInSSRComponentSetup) {
			if (flush === "sync") {
				const ctx = useSSRContext();
				ssrCleanup = ctx.__watcherHandles || (ctx.__watcherHandles = []);
			} else if (!runsImmediately) {
				const watchStopHandle = () => {};
				watchStopHandle.stop = NOOP;
				watchStopHandle.resume = NOOP;
				watchStopHandle.pause = NOOP;
				return watchStopHandle;
			}
		}
		const instance = currentInstance;
		baseWatchOptions.call = (fn, type, args) => callWithAsyncErrorHandling(fn, instance, type, args);
		let isPre = false;
		if (flush === "post") baseWatchOptions.scheduler = (job) => {
			queuePostRenderEffect(job, instance && instance.suspense);
		};
		else if (flush !== "sync") {
			isPre = true;
			baseWatchOptions.scheduler = (job, isFirstRun) => {
				if (isFirstRun) job();
				else queueJob(job);
			};
		}
		baseWatchOptions.augmentJob = (job) => {
			if (cb) job.flags |= 4;
			if (isPre) {
				job.flags |= 2;
				if (instance) {
					job.id = instance.uid;
					job.i = instance;
				}
			}
		};
		const watchHandle = watch$1(source, cb, baseWatchOptions);
		if (isInSSRComponentSetup) {
			if (ssrCleanup) ssrCleanup.push(watchHandle);
			else if (runsImmediately) watchHandle();
		}
		return watchHandle;
	}
	function instanceWatch(source, value, options) {
		const publicThis = this.proxy;
		const getter = isString(source) ? source.includes(".") ? createPathGetter(publicThis, source) : () => publicThis[source] : source.bind(publicThis, publicThis);
		let cb;
		if (isFunction$1(value)) cb = value;
		else {
			cb = value.handler;
			options = value;
		}
		const reset = setCurrentInstance(this);
		const res = doWatch(getter, cb.bind(publicThis), options);
		reset();
		return res;
	}
	function createPathGetter(ctx, path) {
		const segments = path.split(".");
		return () => {
			let cur = ctx;
			for (let i = 0; i < segments.length && cur; i++) cur = cur[segments[i]];
			return cur;
		};
	}
	var pendingMounts = /* @__PURE__ */ new WeakMap();
	var TeleportEndKey = /* @__PURE__ */ Symbol("_vte");
	var isTeleport = (type) => type.__isTeleport;
	var isTeleportDisabled = (props) => props && (props.disabled || props.disabled === "");
	var isTeleportDeferred = (props) => props && (props.defer || props.defer === "");
	var isTargetSVG = (target) => typeof SVGElement !== "undefined" && target instanceof SVGElement;
	var isTargetMathML = (target) => typeof MathMLElement === "function" && target instanceof MathMLElement;
	var resolveTarget = (props, select) => {
		const targetSelector = props && props.to;
		if (isString(targetSelector)) {
			if (!select) return null;
			else return select(targetSelector);
		} else return targetSelector;
	};
	var TeleportImpl = {
		name: "Teleport",
		__isTeleport: true,
		process(n1, n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized, internals) {
			const { mc: mountChildren, pc: patchChildren, pbc: patchBlockChildren, o: { insert, querySelector, createText, createComment, parentNode } } = internals;
			const disabled = isTeleportDisabled(n2.props);
			let { dynamicChildren } = n2;
			const mount = (vnode, container2, anchor2) => {
				if (vnode.shapeFlag & 16) mountChildren(vnode.children, container2, anchor2, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
			};
			const mountToTarget = (vnode = n2) => {
				const disabled2 = isTeleportDisabled(vnode.props);
				const target = vnode.target = resolveTarget(vnode.props, querySelector);
				const targetAnchor = prepareAnchor(target, vnode, createText, insert);
				if (target) {
					if (namespace !== "svg" && isTargetSVG(target)) namespace = "svg";
					else if (namespace !== "mathml" && isTargetMathML(target)) namespace = "mathml";
					if (parentComponent && parentComponent.isCE) (parentComponent.ce._teleportTargets || (parentComponent.ce._teleportTargets = /* @__PURE__ */ new Set())).add(target);
					if (!disabled2) {
						mount(vnode, target, targetAnchor);
						updateCssVars(vnode, false);
					}
				}
			};
			const queuePendingMount = (vnode) => {
				const mountJob = () => {
					if (pendingMounts.get(vnode) !== mountJob) return;
					pendingMounts.delete(vnode);
					if (isTeleportDisabled(vnode.props)) {
						const mountContainer = parentNode(vnode.el) || container;
						mount(vnode, mountContainer, vnode.anchor);
						updateCssVars(vnode, true);
					}
					mountToTarget(vnode);
				};
				pendingMounts.set(vnode, mountJob);
				queuePostRenderEffect(mountJob, parentSuspense);
			};
			if (n1 == null) {
				const placeholder = n2.el = createText("");
				const mainAnchor = n2.anchor = createText("");
				insert(placeholder, container, anchor);
				insert(mainAnchor, container, anchor);
				if (isTeleportDeferred(n2.props) || parentSuspense && parentSuspense.pendingBranch) {
					queuePendingMount(n2);
					return;
				}
				if (disabled) {
					mount(n2, container, mainAnchor);
					updateCssVars(n2, true);
				}
				mountToTarget();
			} else {
				n2.el = n1.el;
				const mainAnchor = n2.anchor = n1.anchor;
				const pendingMount = pendingMounts.get(n1);
				if (pendingMount) {
					pendingMount.flags |= 8;
					pendingMounts.delete(n1);
					queuePendingMount(n2);
					return;
				}
				n2.targetStart = n1.targetStart;
				const target = n2.target = n1.target;
				const targetAnchor = n2.targetAnchor = n1.targetAnchor;
				const wasDisabled = isTeleportDisabled(n1.props);
				const currentContainer = wasDisabled ? container : target;
				const currentAnchor = wasDisabled ? mainAnchor : targetAnchor;
				if (namespace === "svg" || isTargetSVG(target)) namespace = "svg";
				else if (namespace === "mathml" || isTargetMathML(target)) namespace = "mathml";
				if (dynamicChildren) {
					patchBlockChildren(n1.dynamicChildren, dynamicChildren, currentContainer, parentComponent, parentSuspense, namespace, slotScopeIds);
					traverseStaticChildren(n1, n2, true);
				} else if (!optimized) patchChildren(n1, n2, currentContainer, currentAnchor, parentComponent, parentSuspense, namespace, slotScopeIds, false);
				if (disabled) {
					if (!wasDisabled) moveTeleport(n2, container, mainAnchor, internals, 1);
					else if (n2.props && n1.props && n2.props.to !== n1.props.to) n2.props.to = n1.props.to;
				} else if ((n2.props && n2.props.to) !== (n1.props && n1.props.to)) {
					const nextTarget = resolveTarget(n2.props, querySelector);
					if (nextTarget) {
						n2.target = nextTarget;
						moveTeleport(n2, nextTarget, null, internals, 0);
					}
				} else if (wasDisabled) moveTeleport(n2, target, targetAnchor, internals, 1);
				updateCssVars(n2, disabled);
			}
		},
		remove(vnode, parentComponent, parentSuspense, { um: unmount, o: { remove: hostRemove } }, doRemove) {
			const { shapeFlag, children, anchor, targetStart, targetAnchor, target, props } = vnode;
			const disabled = isTeleportDisabled(props);
			const shouldRemove = doRemove || !disabled;
			const pendingMount = pendingMounts.get(vnode);
			if (pendingMount) {
				pendingMount.flags |= 8;
				pendingMounts.delete(vnode);
			}
			if (target) {
				hostRemove(targetStart);
				hostRemove(targetAnchor);
			}
			doRemove && hostRemove(anchor);
			if (!pendingMount && (disabled || target) && shapeFlag & 16) for (let i = 0; i < children.length; i++) {
				const child = children[i];
				unmount(child, parentComponent, parentSuspense, shouldRemove, !!child.dynamicChildren);
			}
		},
		move: moveTeleport,
		hydrate: hydrateTeleport
	};
	function moveTeleport(vnode, container, parentAnchor, { o: { insert }, m: move }, moveType = 2) {
		if (moveType === 0) insert(vnode.targetAnchor, container, parentAnchor);
		const { el, anchor, shapeFlag, children, props } = vnode;
		const isReorder = moveType === 2;
		if (isReorder) insert(el, container, parentAnchor);
		if (!pendingMounts.has(vnode) && (!isReorder || isTeleportDisabled(props))) {
			if (shapeFlag & 16) for (let i = 0; i < children.length; i++) move(children[i], container, parentAnchor, 2);
		}
		if (isReorder) insert(anchor, container, parentAnchor);
	}
	function hydrateTeleport(node, vnode, parentComponent, parentSuspense, slotScopeIds, optimized, { o: { nextSibling, parentNode, querySelector, insert, createText } }, hydrateChildren) {
		function hydrateAnchor(target2, targetNode) {
			let targetAnchor = targetNode;
			while (targetAnchor) {
				if (targetAnchor && targetAnchor.nodeType === 8) {
					if (targetAnchor.data === "teleport start anchor") vnode.targetStart = targetAnchor;
					else if (targetAnchor.data === "teleport anchor") {
						vnode.targetAnchor = targetAnchor;
						target2._lpa = vnode.targetAnchor && nextSibling(vnode.targetAnchor);
						break;
					}
				}
				targetAnchor = nextSibling(targetAnchor);
			}
		}
		function hydrateDisabledTeleport(node2, vnode2) {
			vnode2.anchor = hydrateChildren(nextSibling(node2), vnode2, parentNode(node2), parentComponent, parentSuspense, slotScopeIds, optimized);
		}
		const target = vnode.target = resolveTarget(vnode.props, querySelector);
		const disabled = isTeleportDisabled(vnode.props);
		if (target) {
			const targetNode = target._lpa || target.firstChild;
			if (vnode.shapeFlag & 16) {
				if (disabled) {
					hydrateDisabledTeleport(node, vnode);
					hydrateAnchor(target, targetNode);
					if (!vnode.targetAnchor) prepareAnchor(target, vnode, createText, insert, parentNode(node) === target ? node : null);
				} else {
					vnode.anchor = nextSibling(node);
					hydrateAnchor(target, targetNode);
					if (!vnode.targetAnchor) prepareAnchor(target, vnode, createText, insert);
					hydrateChildren(targetNode && nextSibling(targetNode), vnode, target, parentComponent, parentSuspense, slotScopeIds, optimized);
				}
			}
			updateCssVars(vnode, disabled);
		} else if (disabled) {
			if (vnode.shapeFlag & 16) {
				hydrateDisabledTeleport(node, vnode);
				vnode.targetStart = node;
				vnode.targetAnchor = nextSibling(node);
			}
		}
		return vnode.anchor && nextSibling(vnode.anchor);
	}
	var Teleport = TeleportImpl;
	function updateCssVars(vnode, isDisabled) {
		const ctx = vnode.ctx;
		if (ctx && ctx.ut) {
			let node, anchor;
			if (isDisabled) {
				node = vnode.el;
				anchor = vnode.anchor;
			} else {
				node = vnode.targetStart;
				anchor = vnode.targetAnchor;
			}
			while (node && node !== anchor) {
				if (node.nodeType === 1) node.setAttribute("data-v-owner", ctx.uid);
				node = node.nextSibling;
			}
			ctx.ut();
		}
	}
	function prepareAnchor(target, vnode, createText, insert, anchor = null) {
		const targetStart = vnode.targetStart = createText("");
		const targetAnchor = vnode.targetAnchor = createText("");
		targetStart[TeleportEndKey] = targetAnchor;
		if (target) {
			insert(targetStart, target, anchor);
			insert(targetAnchor, target, anchor);
		}
		return targetAnchor;
	}
	var leaveCbKey = /* @__PURE__ */ Symbol("_leaveCb");
	function findNonCommentChild(children) {
		let child = children[0];
		if (children.length > 1) {
			for (const c of children) if (c.type !== Comment) {
				child = c;
				break;
			}
		}
		return child;
	}
	function getInnerChild$1(vnode) {
		if (!isKeepAlive(vnode)) {
			if (isTeleport(vnode.type) && vnode.children) return findNonCommentChild(vnode.children);
			return vnode;
		}
		if (vnode.component) return vnode.component.subTree;
		const { shapeFlag, children } = vnode;
		if (children) {
			if (shapeFlag & 16) return children[0];
			if (shapeFlag & 32 && isFunction$1(children.default)) return children.default();
		}
	}
	function setTransitionHooks(vnode, hooks) {
		if (vnode.shapeFlag & 6 && vnode.component) {
			vnode.transition = hooks;
			const subTree = vnode.component.subTree;
			setTransitionHooks(isTeleport(subTree.type) ? getInnerChild$1(subTree) || subTree : subTree, hooks);
		} else if (vnode.shapeFlag & 128) {
			vnode.ssContent.transition = hooks.clone(vnode.ssContent);
			vnode.ssFallback.transition = hooks.clone(vnode.ssFallback);
		} else vnode.transition = hooks;
	}
	// @__NO_SIDE_EFFECTS__
	function defineComponent(options, extraOptions) {
		return isFunction$1(options) ? /* @__PURE__ */ (() => extend({ name: options.name }, extraOptions, { setup: options }))() : options;
	}
	function markAsyncBoundary(instance) {
		instance.ids = [
			instance.ids[0] + instance.ids[2]++ + "-",
			0,
			0
		];
	}
	function isTemplateRefKey(refs, key) {
		let desc;
		return !!((desc = Object.getOwnPropertyDescriptor(refs, key)) && !desc.configurable);
	}
	var pendingSetRefMap = /* @__PURE__ */ new WeakMap();
	function setRef(rawRef, oldRawRef, parentSuspense, vnode, isUnmount = false) {
		if (isArray$1(rawRef)) {
			rawRef.forEach((r, i) => setRef(r, oldRawRef && (isArray$1(oldRawRef) ? oldRawRef[i] : oldRawRef), parentSuspense, vnode, isUnmount));
			return;
		}
		if (isAsyncWrapper(vnode) && !isUnmount) {
			if (vnode.shapeFlag & 512 && vnode.type.__asyncResolved && vnode.component.subTree.component) setRef(rawRef, oldRawRef, parentSuspense, vnode.component.subTree);
			return;
		}
		const refValue = vnode.shapeFlag & 4 ? getComponentPublicInstance(vnode.component) : vnode.el;
		const value = isUnmount ? null : refValue;
		const { i: owner, r: ref } = rawRef;
		const oldRef = oldRawRef && oldRawRef.r;
		const refs = owner.refs === EMPTY_OBJ ? owner.refs = {} : owner.refs;
		const setupState = owner.setupState;
		const rawSetupState = /* @__PURE__ */ toRaw(setupState);
		const canSetSetupRef = setupState === EMPTY_OBJ ? NO : (key) => {
			if (isTemplateRefKey(refs, key)) return false;
			return hasOwn(rawSetupState, key);
		};
		const canSetRef = (ref2, key) => {
			if (key && isTemplateRefKey(refs, key)) return false;
			return true;
		};
		if (oldRef != null && oldRef !== ref) {
			invalidatePendingSetRef(oldRawRef);
			if (isString(oldRef)) {
				refs[oldRef] = null;
				if (canSetSetupRef(oldRef)) setupState[oldRef] = null;
			} else if (/* @__PURE__ */ isRef(oldRef)) {
				const oldRawRefAtom = oldRawRef;
				if (canSetRef(oldRef, oldRawRefAtom.k)) oldRef.value = null;
				if (oldRawRefAtom.k) refs[oldRawRefAtom.k] = null;
			}
		}
		if (isFunction$1(ref)) callWithErrorHandling(ref, owner, 12, [value, refs]);
		else {
			const _isString = isString(ref);
			const _isRef = /* @__PURE__ */ isRef(ref);
			if (_isString || _isRef) {
				const doSet = () => {
					if (rawRef.f) {
						const existing = _isString ? canSetSetupRef(ref) ? setupState[ref] : refs[ref] : canSetRef(ref) || !rawRef.k ? ref.value : refs[rawRef.k];
						if (isUnmount) isArray$1(existing) && remove(existing, refValue);
						else if (!isArray$1(existing)) {
							if (_isString) {
								refs[ref] = [refValue];
								if (canSetSetupRef(ref)) setupState[ref] = refs[ref];
							} else {
								const newVal = [refValue];
								if (canSetRef(ref, rawRef.k)) ref.value = newVal;
								if (rawRef.k) refs[rawRef.k] = newVal;
							}
						} else if (!existing.includes(refValue)) existing.push(refValue);
					} else if (_isString) {
						refs[ref] = value;
						if (canSetSetupRef(ref)) setupState[ref] = value;
					} else if (_isRef) {
						if (canSetRef(ref, rawRef.k)) ref.value = value;
						if (rawRef.k) refs[rawRef.k] = value;
					}
				};
				if (value) {
					const job = () => {
						doSet();
						pendingSetRefMap.delete(rawRef);
					};
					job.id = -1;
					pendingSetRefMap.set(rawRef, job);
					queuePostRenderEffect(job, parentSuspense);
				} else {
					invalidatePendingSetRef(rawRef);
					doSet();
				}
			}
		}
	}
	function invalidatePendingSetRef(rawRef) {
		const pendingSetRef = pendingSetRefMap.get(rawRef);
		if (pendingSetRef) {
			pendingSetRef.flags |= 8;
			pendingSetRefMap.delete(rawRef);
		}
	}
	getGlobalThis().requestIdleCallback;
	getGlobalThis().cancelIdleCallback;
	var isAsyncWrapper = (i) => !!i.type.__asyncLoader;
	var isKeepAlive = (vnode) => vnode.type.__isKeepAlive;
	function onActivated(hook, target) {
		registerKeepAliveHook(hook, "a", target);
	}
	function onDeactivated(hook, target) {
		registerKeepAliveHook(hook, "da", target);
	}
	function registerKeepAliveHook(hook, type, target = currentInstance) {
		const wrappedHook = hook.__wdc || (hook.__wdc = () => {
			let current = target;
			while (current) {
				if (current.isDeactivated) return;
				current = current.parent;
			}
			return hook();
		});
		injectHook(type, wrappedHook, target);
		if (target) {
			let current = target.parent;
			while (current && current.parent) {
				if (isKeepAlive(current.parent.vnode)) injectToKeepAliveRoot(wrappedHook, type, target, current);
				current = current.parent;
			}
		}
	}
	function injectToKeepAliveRoot(hook, type, target, keepAliveRoot) {
		const injected = injectHook(type, hook, keepAliveRoot, true);
		onUnmounted(() => {
			remove(keepAliveRoot[type], injected);
		}, target);
	}
	function injectHook(type, hook, target = currentInstance, prepend = false) {
		if (target) {
			const hooks = target[type] || (target[type] = []);
			const wrappedHook = hook.__weh || (hook.__weh = (...args) => {
				pauseTracking();
				const reset = setCurrentInstance(target);
				const res = callWithAsyncErrorHandling(hook, target, type, args);
				reset();
				resetTracking();
				return res;
			});
			if (prepend) hooks.unshift(wrappedHook);
			else hooks.push(wrappedHook);
			return wrappedHook;
		}
	}
	var createHook = (lifecycle) => (hook, target = currentInstance) => {
		if (!isInSSRComponentSetup || lifecycle === "sp") injectHook(lifecycle, (...args) => hook(...args), target);
	};
	var onBeforeMount = createHook("bm");
	var onMounted = createHook("m");
	var onBeforeUpdate = createHook("bu");
	var onUpdated = createHook("u");
	var onBeforeUnmount = createHook("bum");
	var onUnmounted = createHook("um");
	var onServerPrefetch = createHook("sp");
	var onRenderTriggered = createHook("rtg");
	var onRenderTracked = createHook("rtc");
	function onErrorCaptured(hook, target = currentInstance) {
		injectHook("ec", hook, target);
	}
	var NULL_DYNAMIC_COMPONENT = /* @__PURE__ */ Symbol.for("v-ndc");
	function renderList(source, renderItem, cache, index) {
		let ret;
		const cached = cache && cache[index];
		const sourceIsArray = isArray$1(source);
		if (sourceIsArray || isString(source)) {
			const sourceIsReactiveArray = sourceIsArray && /* @__PURE__ */ isReactive(source);
			let needsWrap = false;
			let isReadonlySource = false;
			if (sourceIsReactiveArray) {
				needsWrap = !/* @__PURE__ */ isShallow(source);
				isReadonlySource = /* @__PURE__ */ isReadonly(source);
				source = shallowReadArray(source);
			}
			ret = new Array(source.length);
			for (let i = 0, l = source.length; i < l; i++) ret[i] = renderItem(needsWrap ? isReadonlySource ? toReadonly(toReactive(source[i])) : toReactive(source[i]) : source[i], i, void 0, cached && cached[i]);
		} else if (typeof source === "number") {
			ret = new Array(source);
			for (let i = 0; i < source; i++) ret[i] = renderItem(i + 1, i, void 0, cached && cached[i]);
		} else if (isObject(source)) {
			if (source[Symbol.iterator]) ret = Array.from(source, (item, i) => renderItem(item, i, void 0, cached && cached[i]));
			else {
				const keys = Object.keys(source);
				ret = new Array(keys.length);
				for (let i = 0, l = keys.length; i < l; i++) {
					const key = keys[i];
					ret[i] = renderItem(source[key], key, i, cached && cached[i]);
				}
			}
		} else ret = [];
		if (cache) cache[index] = ret;
		return ret;
	}
	var getPublicInstance = (i) => {
		if (!i) return null;
		if (isStatefulComponent(i)) return getComponentPublicInstance(i);
		return getPublicInstance(i.parent);
	};
	var publicPropertiesMap = /* @__PURE__ */ extend(/* @__PURE__ */ Object.create(null), {
		$: (i) => i,
		$el: (i) => i.vnode.el,
		$data: (i) => i.data,
		$props: (i) => i.props,
		$attrs: (i) => i.attrs,
		$slots: (i) => i.slots,
		$refs: (i) => i.refs,
		$parent: (i) => getPublicInstance(i.parent),
		$root: (i) => getPublicInstance(i.root),
		$host: (i) => i.ce,
		$emit: (i) => i.emit,
		$options: (i) => resolveMergedOptions(i),
		$forceUpdate: (i) => i.f || (i.f = () => {
			queueJob(i.update);
		}),
		$nextTick: (i) => i.n || (i.n = nextTick.bind(i.proxy)),
		$watch: (i) => instanceWatch.bind(i)
	});
	var hasSetupBinding = (state, key) => state !== EMPTY_OBJ && !state.__isScriptSetup && hasOwn(state, key);
	var PublicInstanceProxyHandlers = {
		get({ _: instance }, key) {
			if (key === "__v_skip") return true;
			const { ctx, setupState, data, props, accessCache, type, appContext } = instance;
			if (key[0] !== "$") {
				const n = accessCache[key];
				if (n !== void 0) switch (n) {
					case 1: return setupState[key];
					case 2: return data[key];
					case 4: return ctx[key];
					case 3: return props[key];
				}
				else if (hasSetupBinding(setupState, key)) {
					accessCache[key] = 1;
					return setupState[key];
				} else if (data !== EMPTY_OBJ && hasOwn(data, key)) {
					accessCache[key] = 2;
					return data[key];
				} else if (hasOwn(props, key)) {
					accessCache[key] = 3;
					return props[key];
				} else if (ctx !== EMPTY_OBJ && hasOwn(ctx, key)) {
					accessCache[key] = 4;
					return ctx[key];
				} else if (shouldCacheAccess) accessCache[key] = 0;
			}
			const publicGetter = publicPropertiesMap[key];
			let cssModule, globalProperties;
			if (publicGetter) {
				if (key === "$attrs") track(instance.attrs, "get", "");
				return publicGetter(instance);
			} else if ((cssModule = type.__cssModules) && (cssModule = cssModule[key])) return cssModule;
			else if (ctx !== EMPTY_OBJ && hasOwn(ctx, key)) {
				accessCache[key] = 4;
				return ctx[key];
			} else if (globalProperties = appContext.config.globalProperties, hasOwn(globalProperties, key)) return globalProperties[key];
		},
		set({ _: instance }, key, value) {
			const { data, setupState, ctx } = instance;
			if (hasSetupBinding(setupState, key)) {
				setupState[key] = value;
				return true;
			} else if (data !== EMPTY_OBJ && hasOwn(data, key)) {
				data[key] = value;
				return true;
			} else if (hasOwn(instance.props, key)) return false;
			if (key[0] === "$" && key.slice(1) in instance) return false;
			else ctx[key] = value;
			return true;
		},
		has({ _: { data, setupState, accessCache, ctx, appContext, props, type } }, key) {
			let cssModules;
			return !!(accessCache[key] || data !== EMPTY_OBJ && key[0] !== "$" && hasOwn(data, key) || hasSetupBinding(setupState, key) || hasOwn(props, key) || hasOwn(ctx, key) || hasOwn(publicPropertiesMap, key) || hasOwn(appContext.config.globalProperties, key) || (cssModules = type.__cssModules) && cssModules[key]);
		},
		defineProperty(target, key, descriptor) {
			if (descriptor.get != null) target._.accessCache[key] = 0;
			else if (hasOwn(descriptor, "value")) this.set(target, key, descriptor.value, null);
			return Reflect.defineProperty(target, key, descriptor);
		}
	};
	function normalizePropsOrEmits(props) {
		return isArray$1(props) ? props.reduce((normalized, p) => (normalized[p] = null, normalized), {}) : props;
	}
	var shouldCacheAccess = true;
	function applyOptions(instance) {
		const options = resolveMergedOptions(instance);
		const publicThis = instance.proxy;
		const ctx = instance.ctx;
		shouldCacheAccess = false;
		if (options.beforeCreate) callHook(options.beforeCreate, instance, "bc");
		const { data: dataOptions, computed: computedOptions, methods, watch: watchOptions, provide: provideOptions, inject: injectOptions, created, beforeMount, mounted, beforeUpdate, updated, activated, deactivated, beforeDestroy, beforeUnmount, destroyed, unmounted, render, renderTracked, renderTriggered, errorCaptured, serverPrefetch, expose, inheritAttrs, components, directives, filters } = options;
		const checkDuplicateProperties = null;
		if (injectOptions) resolveInjections(injectOptions, ctx, checkDuplicateProperties);
		if (methods) for (const key in methods) {
			const methodHandler = methods[key];
			if (isFunction$1(methodHandler)) ctx[key] = methodHandler.bind(publicThis);
		}
		if (dataOptions) {
			const data = dataOptions.call(publicThis, publicThis);
			if (!isObject(data)) {} else instance.data = /* @__PURE__ */ reactive(data);
		}
		shouldCacheAccess = true;
		if (computedOptions) for (const key in computedOptions) {
			const opt = computedOptions[key];
			const c = computed({
				get: isFunction$1(opt) ? opt.bind(publicThis, publicThis) : isFunction$1(opt.get) ? opt.get.bind(publicThis, publicThis) : NOOP,
				set: !isFunction$1(opt) && isFunction$1(opt.set) ? opt.set.bind(publicThis) : NOOP
			});
			Object.defineProperty(ctx, key, {
				enumerable: true,
				configurable: true,
				get: () => c.value,
				set: (v) => c.value = v
			});
		}
		if (watchOptions) for (const key in watchOptions) createWatcher(watchOptions[key], ctx, publicThis, key);
		if (provideOptions) {
			const provides = isFunction$1(provideOptions) ? provideOptions.call(publicThis) : provideOptions;
			Reflect.ownKeys(provides).forEach((key) => {
				provide(key, provides[key]);
			});
		}
		if (created) callHook(created, instance, "c");
		function registerLifecycleHook(register, hook) {
			if (isArray$1(hook)) hook.forEach((_hook) => register(_hook.bind(publicThis)));
			else if (hook) register(hook.bind(publicThis));
		}
		registerLifecycleHook(onBeforeMount, beforeMount);
		registerLifecycleHook(onMounted, mounted);
		registerLifecycleHook(onBeforeUpdate, beforeUpdate);
		registerLifecycleHook(onUpdated, updated);
		registerLifecycleHook(onActivated, activated);
		registerLifecycleHook(onDeactivated, deactivated);
		registerLifecycleHook(onErrorCaptured, errorCaptured);
		registerLifecycleHook(onRenderTracked, renderTracked);
		registerLifecycleHook(onRenderTriggered, renderTriggered);
		registerLifecycleHook(onBeforeUnmount, beforeUnmount);
		registerLifecycleHook(onUnmounted, unmounted);
		registerLifecycleHook(onServerPrefetch, serverPrefetch);
		if (isArray$1(expose)) {
			if (expose.length) {
				const exposed = instance.exposed || (instance.exposed = {});
				expose.forEach((key) => {
					Object.defineProperty(exposed, key, {
						get: () => publicThis[key],
						set: (val) => publicThis[key] = val,
						enumerable: true
					});
				});
			} else if (!instance.exposed) instance.exposed = {};
		}
		if (render && instance.render === NOOP) instance.render = render;
		if (inheritAttrs != null) instance.inheritAttrs = inheritAttrs;
		if (components) instance.components = components;
		if (directives) instance.directives = directives;
		if (serverPrefetch) markAsyncBoundary(instance);
	}
	function resolveInjections(injectOptions, ctx, checkDuplicateProperties = NOOP) {
		if (isArray$1(injectOptions)) injectOptions = normalizeInject(injectOptions);
		for (const key in injectOptions) {
			const opt = injectOptions[key];
			let injected;
			if (isObject(opt)) {
				if ("default" in opt) injected = inject(opt.from || key, opt.default, true);
				else injected = inject(opt.from || key);
			} else injected = inject(opt);
			if (/* @__PURE__ */ isRef(injected)) Object.defineProperty(ctx, key, {
				enumerable: true,
				configurable: true,
				get: () => injected.value,
				set: (v) => injected.value = v
			});
			else ctx[key] = injected;
		}
	}
	function callHook(hook, instance, type) {
		callWithAsyncErrorHandling(isArray$1(hook) ? hook.map((h) => h.bind(instance.proxy)) : hook.bind(instance.proxy), instance, type);
	}
	function createWatcher(raw, ctx, publicThis, key) {
		let getter = key.includes(".") ? createPathGetter(publicThis, key) : () => publicThis[key];
		if (isString(raw)) {
			const handler = ctx[raw];
			if (isFunction$1(handler)) watch(getter, handler);
		} else if (isFunction$1(raw)) watch(getter, raw.bind(publicThis));
		else if (isObject(raw)) {
			if (isArray$1(raw)) raw.forEach((r) => createWatcher(r, ctx, publicThis, key));
			else {
				const handler = isFunction$1(raw.handler) ? raw.handler.bind(publicThis) : ctx[raw.handler];
				if (isFunction$1(handler)) watch(getter, handler, raw);
			}
		}
	}
	function resolveMergedOptions(instance) {
		const base = instance.type;
		const { mixins, extends: extendsOptions } = base;
		const { mixins: globalMixins, optionsCache: cache, config: { optionMergeStrategies } } = instance.appContext;
		const cached = cache.get(base);
		let resolved;
		if (cached) resolved = cached;
		else if (!globalMixins.length && !mixins && !extendsOptions) resolved = base;
		else {
			resolved = {};
			if (globalMixins.length) globalMixins.forEach((m) => mergeOptions$1(resolved, m, optionMergeStrategies, true));
			mergeOptions$1(resolved, base, optionMergeStrategies);
		}
		if (isObject(base)) cache.set(base, resolved);
		return resolved;
	}
	function mergeOptions$1(to, from, strats, asMixin = false) {
		const { mixins, extends: extendsOptions } = from;
		if (extendsOptions) mergeOptions$1(to, extendsOptions, strats, true);
		if (mixins) mixins.forEach((m) => mergeOptions$1(to, m, strats, true));
		for (const key in from) if (asMixin && key === "expose") {} else {
			const strat = internalOptionMergeStrats[key] || strats && strats[key];
			to[key] = strat ? strat(to[key], from[key]) : from[key];
		}
		return to;
	}
	var internalOptionMergeStrats = {
		data: mergeDataFn,
		props: mergeEmitsOrPropsOptions,
		emits: mergeEmitsOrPropsOptions,
		methods: mergeObjectOptions,
		computed: mergeObjectOptions,
		beforeCreate: mergeAsArray,
		created: mergeAsArray,
		beforeMount: mergeAsArray,
		mounted: mergeAsArray,
		beforeUpdate: mergeAsArray,
		updated: mergeAsArray,
		beforeDestroy: mergeAsArray,
		beforeUnmount: mergeAsArray,
		destroyed: mergeAsArray,
		unmounted: mergeAsArray,
		activated: mergeAsArray,
		deactivated: mergeAsArray,
		errorCaptured: mergeAsArray,
		serverPrefetch: mergeAsArray,
		components: mergeObjectOptions,
		directives: mergeObjectOptions,
		watch: mergeWatchOptions,
		provide: mergeDataFn,
		inject: mergeInject
	};
	function mergeDataFn(to, from) {
		if (!from) return to;
		if (!to) return from;
		return function mergedDataFn() {
			return extend(isFunction$1(to) ? to.call(this, this) : to, isFunction$1(from) ? from.call(this, this) : from);
		};
	}
	function mergeInject(to, from) {
		return mergeObjectOptions(normalizeInject(to), normalizeInject(from));
	}
	function normalizeInject(raw) {
		if (isArray$1(raw)) {
			const res = {};
			for (let i = 0; i < raw.length; i++) res[raw[i]] = raw[i];
			return res;
		}
		return raw;
	}
	function mergeAsArray(to, from) {
		return to ? [...new Set([].concat(to, from))] : from;
	}
	function mergeObjectOptions(to, from) {
		return to ? extend(/* @__PURE__ */ Object.create(null), to, from) : from;
	}
	function mergeEmitsOrPropsOptions(to, from) {
		if (to) {
			if (isArray$1(to) && isArray$1(from)) return [.../* @__PURE__ */ new Set([...to, ...from])];
			return extend(/* @__PURE__ */ Object.create(null), normalizePropsOrEmits(to), normalizePropsOrEmits(from != null ? from : {}));
		} else return from;
	}
	function mergeWatchOptions(to, from) {
		if (!to) return from;
		if (!from) return to;
		const merged = extend(/* @__PURE__ */ Object.create(null), to);
		for (const key in from) merged[key] = mergeAsArray(to[key], from[key]);
		return merged;
	}
	function createAppContext() {
		return {
			app: null,
			config: {
				isNativeTag: NO,
				performance: false,
				globalProperties: {},
				optionMergeStrategies: {},
				errorHandler: void 0,
				warnHandler: void 0,
				compilerOptions: {}
			},
			mixins: [],
			components: {},
			directives: {},
			provides: /* @__PURE__ */ Object.create(null),
			optionsCache: /* @__PURE__ */ new WeakMap(),
			propsCache: /* @__PURE__ */ new WeakMap(),
			emitsCache: /* @__PURE__ */ new WeakMap()
		};
	}
	var uid$1 = 0;
	function createAppAPI(render, hydrate) {
		return function createApp(rootComponent, rootProps = null) {
			if (!isFunction$1(rootComponent)) rootComponent = extend({}, rootComponent);
			if (rootProps != null && !isObject(rootProps)) rootProps = null;
			const context = createAppContext();
			const installedPlugins = /* @__PURE__ */ new WeakSet();
			const pluginCleanupFns = [];
			let isMounted = false;
			const app = context.app = {
				_uid: uid$1++,
				_component: rootComponent,
				_props: rootProps,
				_container: null,
				_context: context,
				_instance: null,
				version,
				get config() {
					return context.config;
				},
				set config(v) {},
				use(plugin, ...options) {
					if (installedPlugins.has(plugin)) {} else if (plugin && isFunction$1(plugin.install)) {
						installedPlugins.add(plugin);
						plugin.install(app, ...options);
					} else if (isFunction$1(plugin)) {
						installedPlugins.add(plugin);
						plugin(app, ...options);
					}
					return app;
				},
				mixin(mixin) {
					if (!context.mixins.includes(mixin)) context.mixins.push(mixin);
					return app;
				},
				component(name, component) {
					if (!component) return context.components[name];
					context.components[name] = component;
					return app;
				},
				directive(name, directive) {
					if (!directive) return context.directives[name];
					context.directives[name] = directive;
					return app;
				},
				mount(rootContainer, isHydrate, namespace) {
					if (!isMounted) {
						const vnode = app._ceVNode || createVNode(rootComponent, rootProps);
						vnode.appContext = context;
						if (namespace === true) namespace = "svg";
						else if (namespace === false) namespace = void 0;
						if (isHydrate && hydrate) hydrate(vnode, rootContainer);
						else render(vnode, rootContainer, namespace);
						isMounted = true;
						app._container = rootContainer;
						rootContainer.__vue_app__ = app;
						return getComponentPublicInstance(vnode.component);
					}
				},
				onUnmount(cleanupFn) {
					pluginCleanupFns.push(cleanupFn);
				},
				unmount() {
					if (isMounted) {
						callWithAsyncErrorHandling(pluginCleanupFns, app._instance, 16);
						render(null, app._container);
						delete app._container.__vue_app__;
					}
				},
				provide(key, value) {
					context.provides[key] = value;
					return app;
				},
				runWithContext(fn) {
					const lastApp = currentApp;
					currentApp = app;
					try {
						return fn();
					} finally {
						currentApp = lastApp;
					}
				}
			};
			return app;
		};
	}
	var currentApp = null;
	var getModelModifiers = (props, modelName) => {
		return modelName === "modelValue" || modelName === "model-value" ? props.modelModifiers : props[`${modelName}Modifiers`] || props[`${camelize(modelName)}Modifiers`] || props[`${hyphenate(modelName)}Modifiers`];
	};
	function emit(instance, event, ...rawArgs) {
		if (instance.isUnmounted) return;
		const props = instance.vnode.props || EMPTY_OBJ;
		let args = rawArgs;
		const isModelListener = event.startsWith("update:");
		const modifiers = isModelListener && getModelModifiers(props, event.slice(7));
		if (modifiers) {
			if (modifiers.trim) args = rawArgs.map((a) => isString(a) ? a.trim() : a);
			if (modifiers.number) args = rawArgs.map(looseToNumber);
		}
		let handlerName;
		let handler = props[handlerName = toHandlerKey(event)] || props[handlerName = toHandlerKey(camelize(event))];
		if (!handler && isModelListener) handler = props[handlerName = toHandlerKey(hyphenate(event))];
		if (handler) callWithAsyncErrorHandling(handler, instance, 6, args);
		const onceHandler = props[handlerName + `Once`];
		if (onceHandler) {
			if (!instance.emitted) instance.emitted = {};
			else if (instance.emitted[handlerName]) return;
			instance.emitted[handlerName] = true;
			callWithAsyncErrorHandling(onceHandler, instance, 6, args);
		}
	}
	var mixinEmitsCache = /* @__PURE__ */ new WeakMap();
	function normalizeEmitsOptions(comp, appContext, asMixin = false) {
		const cache = asMixin ? mixinEmitsCache : appContext.emitsCache;
		const cached = cache.get(comp);
		if (cached !== void 0) return cached;
		const raw = comp.emits;
		let normalized = {};
		let hasExtends = false;
		if (!isFunction$1(comp)) {
			const extendEmits = (raw2) => {
				const normalizedFromExtend = normalizeEmitsOptions(raw2, appContext, true);
				if (normalizedFromExtend) {
					hasExtends = true;
					extend(normalized, normalizedFromExtend);
				}
			};
			if (!asMixin && appContext.mixins.length) appContext.mixins.forEach(extendEmits);
			if (comp.extends) extendEmits(comp.extends);
			if (comp.mixins) comp.mixins.forEach(extendEmits);
		}
		if (!raw && !hasExtends) {
			if (isObject(comp)) cache.set(comp, null);
			return null;
		}
		if (isArray$1(raw)) raw.forEach((key) => normalized[key] = null);
		else extend(normalized, raw);
		if (isObject(comp)) cache.set(comp, normalized);
		return normalized;
	}
	function isEmitListener(options, key) {
		if (!options || !isOn(key)) return false;
		key = key.slice(2);
		key = key === "Once" ? key : key.replace(/Once$/, "");
		return hasOwn(options, key[0].toLowerCase() + key.slice(1)) || hasOwn(options, hyphenate(key)) || hasOwn(options, key);
	}
	function renderComponentRoot(instance) {
		const { type: Component, vnode, proxy, withProxy, propsOptions: [propsOptions], slots, attrs, emit, render, renderCache, props, data, setupState, ctx, inheritAttrs } = instance;
		const prev = setCurrentRenderingInstance(instance);
		let result;
		let fallthroughAttrs;
		try {
			if (vnode.shapeFlag & 4) {
				const proxyToUse = withProxy || proxy;
				const thisProxy = proxyToUse;
				result = normalizeVNode(render.call(thisProxy, proxyToUse, renderCache, props, setupState, data, ctx));
				fallthroughAttrs = attrs;
			} else {
				const render2 = Component;
				result = normalizeVNode(render2.length > 1 ? render2(props, {
					attrs,
					slots,
					emit
				}) : render2(props, null));
				fallthroughAttrs = Component.props ? attrs : getFunctionalFallthrough(attrs);
			}
		} catch (err) {
			blockStack.length = 0;
			handleError(err, instance, 1);
			result = createVNode(Comment);
		}
		let root = result;
		if (fallthroughAttrs && inheritAttrs !== false) {
			const keys = Object.keys(fallthroughAttrs);
			const { shapeFlag } = root;
			if (keys.length) {
				if (shapeFlag & 7) {
					if (propsOptions && keys.some(isModelListener)) fallthroughAttrs = filterModelListeners(fallthroughAttrs, propsOptions);
					root = cloneVNode(root, fallthroughAttrs, false, true);
				}
			}
		}
		if (vnode.dirs) {
			root = cloneVNode(root, null, false, true);
			root.dirs = root.dirs ? root.dirs.concat(vnode.dirs) : vnode.dirs;
		}
		if (vnode.transition) setTransitionHooks(isTeleport(root.type) ? getInnerChild$1(root) || root : root, vnode.transition);
		result = root;
		setCurrentRenderingInstance(prev);
		return result;
	}
	var getFunctionalFallthrough = (attrs) => {
		let res;
		for (const key in attrs) if (key === "class" || key === "style" || isOn(key)) (res || (res = {}))[key] = attrs[key];
		return res;
	};
	var filterModelListeners = (attrs, props) => {
		const res = {};
		for (const key in attrs) if (!isModelListener(key) || !(key.slice(9) in props)) res[key] = attrs[key];
		return res;
	};
	function shouldUpdateComponent(prevVNode, nextVNode, optimized) {
		const { props: prevProps, children: prevChildren, component } = prevVNode;
		const { props: nextProps, children: nextChildren, patchFlag } = nextVNode;
		const emits = component.emitsOptions;
		if (nextVNode.dirs || nextVNode.transition) return true;
		if (optimized && patchFlag >= 0) {
			if (patchFlag & 1024) return true;
			if (patchFlag & 16) {
				if (!prevProps) return !!nextProps;
				return hasPropsChanged(prevProps, nextProps, emits);
			} else if (patchFlag & 8) {
				const dynamicProps = nextVNode.dynamicProps;
				for (let i = 0; i < dynamicProps.length; i++) {
					const key = dynamicProps[i];
					if (hasPropValueChanged(nextProps, prevProps, key) && !isEmitListener(emits, key)) return true;
				}
			}
		} else {
			if (prevChildren || nextChildren) {
				if (!nextChildren || !nextChildren.$stable) return true;
			}
			if (prevProps === nextProps) return false;
			if (!prevProps) return !!nextProps;
			if (!nextProps) return true;
			return hasPropsChanged(prevProps, nextProps, emits);
		}
		return false;
	}
	function hasPropsChanged(prevProps, nextProps, emitsOptions) {
		const nextKeys = Object.keys(nextProps);
		if (nextKeys.length !== Object.keys(prevProps).length) return true;
		for (let i = 0; i < nextKeys.length; i++) {
			const key = nextKeys[i];
			if (hasPropValueChanged(nextProps, prevProps, key) && !isEmitListener(emitsOptions, key)) return true;
		}
		return false;
	}
	function hasPropValueChanged(nextProps, prevProps, key) {
		const nextProp = nextProps[key];
		const prevProp = prevProps[key];
		if (key === "style" && isObject(nextProp) && isObject(prevProp)) return !looseEqual(nextProp, prevProp);
		return nextProp !== prevProp;
	}
	function updateHOCHostEl({ vnode, parent, suspense }, el) {
		while (parent) {
			const root = parent.subTree;
			if (root.suspense && root.suspense.activeBranch === vnode) {
				root.suspense.vnode.el = root.el = el;
				vnode = root;
			}
			if (root === vnode) {
				(vnode = parent.vnode).el = el;
				parent = parent.parent;
			} else break;
		}
		if (suspense && suspense.activeBranch === vnode) suspense.vnode.el = el;
	}
	var internalObjectProto = {};
	var createInternalObject = () => Object.create(internalObjectProto);
	var isInternalObject = (obj) => Object.getPrototypeOf(obj) === internalObjectProto;
	function initProps(instance, rawProps, isStateful, isSSR = false) {
		const props = {};
		const attrs = createInternalObject();
		instance.propsDefaults = /* @__PURE__ */ Object.create(null);
		setFullProps(instance, rawProps, props, attrs);
		for (const key in instance.propsOptions[0]) if (!(key in props)) props[key] = void 0;
		if (isStateful) instance.props = isSSR ? props : /* @__PURE__ */ shallowReactive(props);
		else if (!instance.type.props) instance.props = attrs;
		else instance.props = props;
		instance.attrs = attrs;
	}
	function updateProps(instance, rawProps, rawPrevProps, optimized) {
		const { props, attrs, vnode: { patchFlag } } = instance;
		const rawCurrentProps = /* @__PURE__ */ toRaw(props);
		const [options] = instance.propsOptions;
		let hasAttrsChanged = false;
		if ((optimized || patchFlag > 0) && !(patchFlag & 16)) {
			if (patchFlag & 8) {
				const propsToUpdate = instance.vnode.dynamicProps;
				for (let i = 0; i < propsToUpdate.length; i++) {
					let key = propsToUpdate[i];
					if (isEmitListener(instance.emitsOptions, key)) continue;
					const value = rawProps[key];
					if (options) {
						if (hasOwn(attrs, key)) {
							if (value !== attrs[key]) {
								attrs[key] = value;
								hasAttrsChanged = true;
							}
						} else {
							const camelizedKey = camelize(key);
							props[camelizedKey] = resolvePropValue(options, rawCurrentProps, camelizedKey, value, instance, false);
						}
					} else if (value !== attrs[key]) {
						attrs[key] = value;
						hasAttrsChanged = true;
					}
				}
			}
		} else {
			if (setFullProps(instance, rawProps, props, attrs)) hasAttrsChanged = true;
			let kebabKey;
			for (const key in rawCurrentProps) if (!rawProps || !hasOwn(rawProps, key) && ((kebabKey = hyphenate(key)) === key || !hasOwn(rawProps, kebabKey))) {
				if (options) {
					if (rawPrevProps && (rawPrevProps[key] !== void 0 || rawPrevProps[kebabKey] !== void 0)) props[key] = resolvePropValue(options, rawCurrentProps, key, void 0, instance, true);
				} else delete props[key];
			}
			if (attrs !== rawCurrentProps) {
				for (const key in attrs) if (!rawProps || !hasOwn(rawProps, key) && true) {
					delete attrs[key];
					hasAttrsChanged = true;
				}
			}
		}
		if (hasAttrsChanged) trigger(instance.attrs, "set", "");
	}
	function setFullProps(instance, rawProps, props, attrs) {
		const [options, needCastKeys] = instance.propsOptions;
		let hasAttrsChanged = false;
		let rawCastValues;
		if (rawProps) for (let key in rawProps) {
			if (isReservedProp(key)) continue;
			const value = rawProps[key];
			let camelKey;
			if (options && hasOwn(options, camelKey = camelize(key))) {
				if (!needCastKeys || !needCastKeys.includes(camelKey)) props[camelKey] = value;
				else (rawCastValues || (rawCastValues = {}))[camelKey] = value;
			} else if (!isEmitListener(instance.emitsOptions, key)) {
				if (!(key in attrs) || value !== attrs[key]) {
					attrs[key] = value;
					hasAttrsChanged = true;
				}
			}
		}
		if (needCastKeys) {
			const rawCurrentProps = /* @__PURE__ */ toRaw(props);
			const castValues = rawCastValues || EMPTY_OBJ;
			for (let i = 0; i < needCastKeys.length; i++) {
				const key = needCastKeys[i];
				props[key] = resolvePropValue(options, rawCurrentProps, key, castValues[key], instance, !hasOwn(castValues, key));
			}
		}
		return hasAttrsChanged;
	}
	function resolvePropValue(options, props, key, value, instance, isAbsent) {
		const opt = options[key];
		if (opt != null) {
			const hasDefault = hasOwn(opt, "default");
			if (hasDefault && value === void 0) {
				const defaultValue = opt.default;
				if (opt.type !== Function && !opt.skipFactory && isFunction$1(defaultValue)) {
					const { propsDefaults } = instance;
					if (key in propsDefaults) value = propsDefaults[key];
					else {
						const reset = setCurrentInstance(instance);
						value = propsDefaults[key] = defaultValue.call(null, props);
						reset();
					}
				} else value = defaultValue;
				if (instance.ce) instance.ce._setProp(key, value);
			}
			if (opt[0]) {
				if (isAbsent && !hasDefault) value = false;
				else if (opt[1] && (value === "" || value === hyphenate(key))) value = true;
			}
		}
		return value;
	}
	var mixinPropsCache = /* @__PURE__ */ new WeakMap();
	function normalizePropsOptions(comp, appContext, asMixin = false) {
		const cache = asMixin ? mixinPropsCache : appContext.propsCache;
		const cached = cache.get(comp);
		if (cached) return cached;
		const raw = comp.props;
		const normalized = {};
		const needCastKeys = [];
		let hasExtends = false;
		if (!isFunction$1(comp)) {
			const extendProps = (raw2) => {
				hasExtends = true;
				const [props, keys] = normalizePropsOptions(raw2, appContext, true);
				extend(normalized, props);
				if (keys) needCastKeys.push(...keys);
			};
			if (!asMixin && appContext.mixins.length) appContext.mixins.forEach(extendProps);
			if (comp.extends) extendProps(comp.extends);
			if (comp.mixins) comp.mixins.forEach(extendProps);
		}
		if (!raw && !hasExtends) {
			if (isObject(comp)) cache.set(comp, EMPTY_ARR);
			return EMPTY_ARR;
		}
		if (isArray$1(raw)) for (let i = 0; i < raw.length; i++) {
			const normalizedKey = camelize(raw[i]);
			if (validatePropName(normalizedKey)) normalized[normalizedKey] = EMPTY_OBJ;
		}
		else if (raw) for (const key in raw) {
			const normalizedKey = camelize(key);
			if (validatePropName(normalizedKey)) {
				const opt = raw[key];
				const prop = normalized[normalizedKey] = isArray$1(opt) || isFunction$1(opt) ? { type: opt } : extend({}, opt);
				const propType = prop.type;
				let shouldCast = false;
				let shouldCastTrue = true;
				if (isArray$1(propType)) for (let index = 0; index < propType.length; ++index) {
					const type = propType[index];
					const typeName = isFunction$1(type) && type.name;
					if (typeName === "Boolean") {
						shouldCast = true;
						break;
					} else if (typeName === "String") shouldCastTrue = false;
				}
				else shouldCast = isFunction$1(propType) && propType.name === "Boolean";
				prop[0] = shouldCast;
				prop[1] = shouldCastTrue;
				if (shouldCast || hasOwn(prop, "default")) needCastKeys.push(normalizedKey);
			}
		}
		const res = [normalized, needCastKeys];
		if (isObject(comp)) cache.set(comp, res);
		return res;
	}
	function validatePropName(key) {
		if (key[0] !== "$" && !isReservedProp(key)) return true;
		return false;
	}
	var isInternalKey = (key) => key === "_" || key === "_ctx" || key === "$stable";
	var normalizeSlotValue = (value) => isArray$1(value) ? value.map(normalizeVNode) : [normalizeVNode(value)];
	var normalizeSlot$1 = (key, rawSlot, ctx) => {
		if (rawSlot._n) return rawSlot;
		const normalized = withCtx((...args) => {
			return normalizeSlotValue(rawSlot(...args));
		}, ctx);
		normalized._c = false;
		return normalized;
	};
	var normalizeObjectSlots = (rawSlots, slots, instance) => {
		const ctx = rawSlots._ctx;
		for (const key in rawSlots) {
			if (isInternalKey(key)) continue;
			const value = rawSlots[key];
			if (isFunction$1(value)) slots[key] = normalizeSlot$1(key, value, ctx);
			else if (value != null) {
				const normalized = normalizeSlotValue(value);
				slots[key] = () => normalized;
			}
		}
	};
	var normalizeVNodeSlots = (instance, children) => {
		const normalized = normalizeSlotValue(children);
		instance.slots.default = () => normalized;
	};
	var assignSlots = (slots, children, optimized) => {
		for (const key in children) if (optimized || !isInternalKey(key)) slots[key] = children[key];
	};
	var initSlots = (instance, children, optimized) => {
		const slots = instance.slots = createInternalObject();
		if (instance.vnode.shapeFlag & 32) {
			const type = children._;
			if (type) {
				assignSlots(slots, children, optimized);
				if (optimized) def(slots, "_", type, true);
			} else normalizeObjectSlots(children, slots);
		} else if (children) normalizeVNodeSlots(instance, children);
	};
	var updateSlots = (instance, children, optimized) => {
		const { vnode, slots } = instance;
		let needDeletionCheck = true;
		let deletionComparisonTarget = EMPTY_OBJ;
		if (vnode.shapeFlag & 32) {
			const type = children._;
			if (type) {
				if (optimized && type === 1) needDeletionCheck = false;
				else assignSlots(slots, children, optimized);
			} else {
				needDeletionCheck = !children.$stable;
				normalizeObjectSlots(children, slots);
			}
			deletionComparisonTarget = children;
		} else if (children) {
			normalizeVNodeSlots(instance, children);
			deletionComparisonTarget = { default: 1 };
		}
		if (needDeletionCheck) {
			for (const key in slots) if (!isInternalKey(key) && deletionComparisonTarget[key] == null) delete slots[key];
		}
	};
	var queuePostRenderEffect = queueEffectWithSuspense;
	function createRenderer(options) {
		return baseCreateRenderer(options);
	}
	function baseCreateRenderer(options, createHydrationFns) {
		const target = getGlobalThis();
		target.__VUE__ = true;
		const { insert: hostInsert, remove: hostRemove, patchProp: hostPatchProp, createElement: hostCreateElement, createText: hostCreateText, createComment: hostCreateComment, setText: hostSetText, setElementText: hostSetElementText, parentNode: hostParentNode, nextSibling: hostNextSibling, setScopeId: hostSetScopeId = NOOP, insertStaticContent: hostInsertStaticContent } = options;
		const patch = (n1, n2, container, anchor = null, parentComponent = null, parentSuspense = null, namespace = void 0, slotScopeIds = null, optimized = !!n2.dynamicChildren) => {
			if (n1 === n2) return;
			if (n1 && !isSameVNodeType(n1, n2)) {
				anchor = getNextHostNode(n1);
				unmount(n1, parentComponent, parentSuspense, true);
				n1 = null;
			}
			if (n2.patchFlag === -2) {
				optimized = false;
				n2.dynamicChildren = null;
			}
			const { type, ref, shapeFlag } = n2;
			switch (type) {
				case Text:
					processText(n1, n2, container, anchor);
					break;
				case Comment:
					processCommentNode(n1, n2, container, anchor);
					break;
				case Static:
					if (n1 == null) mountStaticNode(n2, container, anchor, namespace);
					break;
				case Fragment:
					processFragment(n1, n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
					break;
				default: if (shapeFlag & 1) processElement(n1, n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
				else if (shapeFlag & 6) processComponent(n1, n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
				else if (shapeFlag & 64) type.process(n1, n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized, internals);
				else if (shapeFlag & 128) type.process(n1, n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized, internals);
			}
			if (ref != null && parentComponent) setRef(ref, n1 && n1.ref, parentSuspense, n2 || n1, !n2);
			else if (ref == null && n1 && n1.ref != null) setRef(n1.ref, null, parentSuspense, n1, true);
		};
		const processText = (n1, n2, container, anchor) => {
			if (n1 == null) hostInsert(n2.el = hostCreateText(n2.children), container, anchor);
			else {
				const el = n2.el = n1.el;
				if (n2.children !== n1.children) hostSetText(el, n2.children);
			}
		};
		const processCommentNode = (n1, n2, container, anchor) => {
			if (n1 == null) hostInsert(n2.el = hostCreateComment(n2.children || ""), container, anchor);
			else n2.el = n1.el;
		};
		const mountStaticNode = (n2, container, anchor, namespace) => {
			[n2.el, n2.anchor] = hostInsertStaticContent(n2.children, container, anchor, namespace, n2.el, n2.anchor);
		};
		const moveStaticNode = ({ el, anchor }, container, nextSibling) => {
			let next;
			while (el && el !== anchor) {
				next = hostNextSibling(el);
				hostInsert(el, container, nextSibling);
				el = next;
			}
			hostInsert(anchor, container, nextSibling);
		};
		const removeStaticNode = ({ el, anchor }) => {
			let next;
			while (el && el !== anchor) {
				next = hostNextSibling(el);
				hostRemove(el);
				el = next;
			}
			hostRemove(anchor);
		};
		const processElement = (n1, n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized) => {
			if (n2.type === "svg") namespace = "svg";
			else if (n2.type === "math") namespace = "mathml";
			if (n1 == null) mountElement(n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
			else {
				const customElement = n1.el && n1.el._isVueCE ? n1.el : null;
				try {
					if (customElement) customElement._beginPatch();
					patchElement(n1, n2, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
				} finally {
					if (customElement) customElement._endPatch();
				}
			}
		};
		const mountElement = (vnode, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized) => {
			let el;
			let vnodeHook;
			const { props, shapeFlag, transition, dirs } = vnode;
			el = vnode.el = hostCreateElement(vnode.type, namespace, props && props.is, props);
			if (shapeFlag & 8) hostSetElementText(el, vnode.children);
			else if (shapeFlag & 16) mountChildren(vnode.children, el, null, parentComponent, parentSuspense, resolveChildrenNamespace(vnode, namespace), slotScopeIds, optimized);
			if (dirs) invokeDirectiveHook(vnode, null, parentComponent, "created");
			setScopeId(el, vnode, vnode.scopeId, slotScopeIds, parentComponent);
			if (props) {
				for (const key in props) if (key !== "value" && !isReservedProp(key)) hostPatchProp(el, key, null, props[key], namespace, parentComponent);
				if ("value" in props) hostPatchProp(el, "value", null, props.value, namespace);
				if (vnodeHook = props.onVnodeBeforeMount) invokeVNodeHook(vnodeHook, parentComponent, vnode);
			}
			if (dirs) invokeDirectiveHook(vnode, null, parentComponent, "beforeMount");
			const needCallTransitionHooks = needTransition(parentSuspense, transition);
			if (needCallTransitionHooks) transition.beforeEnter(el);
			hostInsert(el, container, anchor);
			if ((vnodeHook = props && props.onVnodeMounted) || needCallTransitionHooks || dirs) queuePostRenderEffect(() => {
				try {
					vnodeHook && invokeVNodeHook(vnodeHook, parentComponent, vnode);
					needCallTransitionHooks && transition.enter(el);
					dirs && invokeDirectiveHook(vnode, null, parentComponent, "mounted");
				} finally {}
			}, parentSuspense);
		};
		const setScopeId = (el, vnode, scopeId, slotScopeIds, parentComponent) => {
			if (scopeId) hostSetScopeId(el, scopeId);
			if (slotScopeIds) for (let i = 0; i < slotScopeIds.length; i++) hostSetScopeId(el, slotScopeIds[i]);
			if (parentComponent) {
				let subTree = parentComponent.subTree;
				if (vnode === subTree || isSuspense(subTree.type) && (subTree.ssContent === vnode || subTree.ssFallback === vnode)) {
					const parentVNode = parentComponent.vnode;
					setScopeId(el, parentVNode, parentVNode.scopeId, parentVNode.slotScopeIds, parentComponent.parent);
				}
			}
		};
		const mountChildren = (children, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized, start = 0) => {
			for (let i = start; i < children.length; i++) {
				const child = children[i] = optimized ? cloneIfMounted(children[i]) : normalizeVNode(children[i]);
				patch(null, child, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
			}
		};
		const patchElement = (n1, n2, parentComponent, parentSuspense, namespace, slotScopeIds, optimized) => {
			const el = n2.el = n1.el;
			let { patchFlag, dynamicChildren, dirs } = n2;
			patchFlag |= n1.patchFlag & 16;
			const oldProps = n1.props || EMPTY_OBJ;
			const newProps = n2.props || EMPTY_OBJ;
			let vnodeHook;
			parentComponent && toggleRecurse(parentComponent, false);
			if (vnodeHook = newProps.onVnodeBeforeUpdate) invokeVNodeHook(vnodeHook, parentComponent, n2, n1);
			if (dirs) invokeDirectiveHook(n2, n1, parentComponent, "beforeUpdate");
			parentComponent && toggleRecurse(parentComponent, true);
			if (dynamicChildren && (!n1.dynamicChildren || n1.dynamicChildren.length !== dynamicChildren.length)) {
				patchFlag = 0;
				optimized = false;
				dynamicChildren = null;
			}
			if (oldProps.innerHTML && newProps.innerHTML == null || oldProps.textContent && newProps.textContent == null) hostSetElementText(el, "");
			if (dynamicChildren) patchBlockChildren(n1.dynamicChildren, dynamicChildren, el, parentComponent, parentSuspense, resolveChildrenNamespace(n2, namespace), slotScopeIds);
			else if (!optimized) patchChildren(n1, n2, el, null, parentComponent, parentSuspense, resolveChildrenNamespace(n2, namespace), slotScopeIds, false);
			if (patchFlag > 0) {
				if (patchFlag & 16) patchProps(el, oldProps, newProps, parentComponent, namespace);
				else {
					if (patchFlag & 2) {
						if (oldProps.class !== newProps.class) hostPatchProp(el, "class", null, newProps.class, namespace);
					}
					if (patchFlag & 4) hostPatchProp(el, "style", oldProps.style, newProps.style, namespace);
					if (patchFlag & 8) {
						const propsToUpdate = n2.dynamicProps;
						for (let i = 0; i < propsToUpdate.length; i++) {
							const key = propsToUpdate[i];
							const prev = oldProps[key];
							const next = newProps[key];
							if (next !== prev || key === "value") hostPatchProp(el, key, prev, next, namespace, parentComponent);
						}
					}
				}
				if (patchFlag & 1) {
					if (n1.children !== n2.children) hostSetElementText(el, n2.children);
				}
			} else if (!optimized && dynamicChildren == null) patchProps(el, oldProps, newProps, parentComponent, namespace);
			if ((vnodeHook = newProps.onVnodeUpdated) || dirs) queuePostRenderEffect(() => {
				vnodeHook && invokeVNodeHook(vnodeHook, parentComponent, n2, n1);
				dirs && invokeDirectiveHook(n2, n1, parentComponent, "updated");
			}, parentSuspense);
		};
		const patchBlockChildren = (oldChildren, newChildren, fallbackContainer, parentComponent, parentSuspense, namespace, slotScopeIds) => {
			for (let i = 0; i < newChildren.length; i++) {
				const oldVNode = oldChildren[i];
				const newVNode = newChildren[i];
				const container = oldVNode.el && (oldVNode.type === Fragment || !isSameVNodeType(oldVNode, newVNode) || oldVNode.shapeFlag & 198) ? hostParentNode(oldVNode.el) : fallbackContainer;
				patch(oldVNode, newVNode, container, null, parentComponent, parentSuspense, namespace, slotScopeIds, true);
			}
		};
		const patchProps = (el, oldProps, newProps, parentComponent, namespace) => {
			if (oldProps !== newProps) {
				if (oldProps !== EMPTY_OBJ) {
					for (const key in oldProps) if (!isReservedProp(key) && !(key in newProps)) hostPatchProp(el, key, oldProps[key], null, namespace, parentComponent);
				}
				for (const key in newProps) {
					if (isReservedProp(key)) continue;
					const next = newProps[key];
					const prev = oldProps[key];
					if (next !== prev && key !== "value") hostPatchProp(el, key, prev, next, namespace, parentComponent);
				}
				if ("value" in newProps) hostPatchProp(el, "value", oldProps.value, newProps.value, namespace);
			}
		};
		const processFragment = (n1, n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized) => {
			const fragmentStartAnchor = n2.el = n1 ? n1.el : hostCreateText("");
			const fragmentEndAnchor = n2.anchor = n1 ? n1.anchor : hostCreateText("");
			let { patchFlag, dynamicChildren, slotScopeIds: fragmentSlotScopeIds } = n2;
			if (fragmentSlotScopeIds) slotScopeIds = slotScopeIds ? slotScopeIds.concat(fragmentSlotScopeIds) : fragmentSlotScopeIds;
			if (n1 == null) {
				hostInsert(fragmentStartAnchor, container, anchor);
				hostInsert(fragmentEndAnchor, container, anchor);
				mountChildren(n2.children || [], container, fragmentEndAnchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
			} else if (patchFlag > 0 && patchFlag & 64 && dynamicChildren && n1.dynamicChildren && n1.dynamicChildren.length === dynamicChildren.length) {
				patchBlockChildren(n1.dynamicChildren, dynamicChildren, container, parentComponent, parentSuspense, namespace, slotScopeIds);
				if (n2.key != null || parentComponent && n2 === parentComponent.subTree) traverseStaticChildren(n1, n2, true);
			} else patchChildren(n1, n2, container, fragmentEndAnchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
		};
		const processComponent = (n1, n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized) => {
			n2.slotScopeIds = slotScopeIds;
			if (n1 == null) {
				if (n2.shapeFlag & 512) parentComponent.ctx.activate(n2, container, anchor, namespace, optimized);
				else mountComponent(n2, container, anchor, parentComponent, parentSuspense, namespace, optimized);
			} else updateComponent(n1, n2, optimized);
		};
		const mountComponent = (initialVNode, container, anchor, parentComponent, parentSuspense, namespace, optimized) => {
			const instance = initialVNode.component = createComponentInstance(initialVNode, parentComponent, parentSuspense);
			if (isKeepAlive(initialVNode)) instance.ctx.renderer = internals;
			setupComponent(instance, false, optimized);
			if (instance.asyncDep) {
				parentSuspense && parentSuspense.registerDep(instance, setupRenderEffect, optimized);
				if (!initialVNode.el) {
					const placeholder = instance.subTree = createVNode(Comment);
					processCommentNode(null, placeholder, container, anchor);
					initialVNode.placeholder = placeholder.el;
				}
			} else setupRenderEffect(instance, initialVNode, container, anchor, parentSuspense, namespace, optimized);
		};
		const updateComponent = (n1, n2, optimized) => {
			const instance = n2.component = n1.component;
			if (shouldUpdateComponent(n1, n2, optimized)) {
				if (instance.asyncDep && !instance.asyncResolved) {
					updateComponentPreRender(instance, n2, optimized);
					return;
				} else {
					instance.next = n2;
					instance.update();
				}
			} else {
				n2.el = n1.el;
				instance.vnode = n2;
			}
		};
		const setupRenderEffect = (instance, initialVNode, container, anchor, parentSuspense, namespace, optimized) => {
			const componentUpdateFn = () => {
				if (!instance.isMounted) {
					let vnodeHook;
					const { el, props } = initialVNode;
					const { bm, m, parent, root, type } = instance;
					const isAsyncWrapperVNode = isAsyncWrapper(initialVNode);
					toggleRecurse(instance, false);
					if (bm) invokeArrayFns(bm);
					if (!isAsyncWrapperVNode && (vnodeHook = props && props.onVnodeBeforeMount)) invokeVNodeHook(vnodeHook, parent, initialVNode);
					toggleRecurse(instance, true);
					if (el && hydrateNode) {
						const hydrateSubTree = () => {
							instance.subTree = renderComponentRoot(instance);
							hydrateNode(el, instance.subTree, instance, parentSuspense, null);
						};
						if (isAsyncWrapperVNode && type.__asyncHydrate) type.__asyncHydrate(el, instance, hydrateSubTree);
						else hydrateSubTree();
					} else {
						if (root.ce && root.ce._hasShadowRoot()) root.ce._injectChildStyle(type, instance.parent ? instance.parent.type : void 0);
						const subTree = instance.subTree = renderComponentRoot(instance);
						patch(null, subTree, container, anchor, instance, parentSuspense, namespace);
						initialVNode.el = subTree.el;
					}
					if (m) queuePostRenderEffect(m, parentSuspense);
					if (!isAsyncWrapperVNode && (vnodeHook = props && props.onVnodeMounted)) {
						const scopedInitialVNode = initialVNode;
						queuePostRenderEffect(() => invokeVNodeHook(vnodeHook, parent, scopedInitialVNode), parentSuspense);
					}
					if (initialVNode.shapeFlag & 256 || parent && isAsyncWrapper(parent.vnode) && parent.vnode.shapeFlag & 256) instance.a && queuePostRenderEffect(instance.a, parentSuspense);
					instance.isMounted = true;
					initialVNode = container = anchor = null;
				} else {
					let { next, bu, u, parent, vnode } = instance;
					{
						const nonHydratedAsyncRoot = locateNonHydratedAsyncRoot(instance);
						if (nonHydratedAsyncRoot) {
							if (next) {
								next.el = vnode.el;
								updateComponentPreRender(instance, next, optimized);
							}
							nonHydratedAsyncRoot.asyncDep.then(() => {
								queuePostRenderEffect(() => {
									if (!instance.isUnmounted) update();
								}, parentSuspense);
							});
							return;
						}
					}
					let originNext = next;
					let vnodeHook;
					toggleRecurse(instance, false);
					if (next) {
						next.el = vnode.el;
						updateComponentPreRender(instance, next, optimized);
					} else next = vnode;
					if (bu) invokeArrayFns(bu);
					if (vnodeHook = next.props && next.props.onVnodeBeforeUpdate) invokeVNodeHook(vnodeHook, parent, next, vnode);
					toggleRecurse(instance, true);
					const nextTree = renderComponentRoot(instance);
					const prevTree = instance.subTree;
					instance.subTree = nextTree;
					patch(prevTree, nextTree, hostParentNode(prevTree.el), getNextHostNode(prevTree), instance, parentSuspense, namespace);
					next.el = nextTree.el;
					if (originNext === null) updateHOCHostEl(instance, nextTree.el);
					if (u) queuePostRenderEffect(u, parentSuspense);
					if (vnodeHook = next.props && next.props.onVnodeUpdated) queuePostRenderEffect(() => invokeVNodeHook(vnodeHook, parent, next, vnode), parentSuspense);
				}
			};
			instance.scope.on();
			const effect = instance.effect = new ReactiveEffect(componentUpdateFn);
			instance.scope.off();
			const update = instance.update = effect.run.bind(effect);
			const job = instance.job = effect.runIfDirty.bind(effect);
			job.i = instance;
			job.id = instance.uid;
			effect.scheduler = () => queueJob(job);
			toggleRecurse(instance, true);
			update();
		};
		const updateComponentPreRender = (instance, nextVNode, optimized) => {
			nextVNode.component = instance;
			const prevProps = instance.vnode.props;
			instance.vnode = nextVNode;
			instance.next = null;
			updateProps(instance, nextVNode.props, prevProps, optimized);
			updateSlots(instance, nextVNode.children, optimized);
			pauseTracking();
			flushPreFlushCbs(instance);
			resetTracking();
		};
		const patchChildren = (n1, n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized = false) => {
			const c1 = n1 && n1.children;
			const prevShapeFlag = n1 ? n1.shapeFlag : 0;
			const c2 = n2.children;
			const { patchFlag, shapeFlag } = n2;
			if (patchFlag > 0) {
				if (patchFlag & 128) {
					patchKeyedChildren(c1, c2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
					return;
				} else if (patchFlag & 256) {
					patchUnkeyedChildren(c1, c2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
					return;
				}
			}
			if (shapeFlag & 8) {
				if (prevShapeFlag & 16) unmountChildren(c1, parentComponent, parentSuspense);
				if (c2 !== c1) hostSetElementText(container, c2);
			} else if (prevShapeFlag & 16) {
				if (shapeFlag & 16) patchKeyedChildren(c1, c2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
				else unmountChildren(c1, parentComponent, parentSuspense, true);
			} else {
				if (prevShapeFlag & 8) hostSetElementText(container, "");
				if (shapeFlag & 16) mountChildren(c2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
			}
		};
		const patchUnkeyedChildren = (c1, c2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized) => {
			c1 = c1 || EMPTY_ARR;
			c2 = c2 || EMPTY_ARR;
			const oldLength = c1.length;
			const newLength = c2.length;
			const commonLength = Math.min(oldLength, newLength);
			let i;
			for (i = 0; i < commonLength; i++) {
				const nextChild = c2[i] = optimized ? cloneIfMounted(c2[i]) : normalizeVNode(c2[i]);
				patch(c1[i], nextChild, container, null, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
			}
			if (oldLength > newLength) unmountChildren(c1, parentComponent, parentSuspense, true, false, commonLength);
			else mountChildren(c2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized, commonLength);
		};
		const patchKeyedChildren = (c1, c2, container, parentAnchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized) => {
			let i = 0;
			const l2 = c2.length;
			let e1 = c1.length - 1;
			let e2 = l2 - 1;
			while (i <= e1 && i <= e2) {
				const n1 = c1[i];
				const n2 = c2[i] = optimized ? cloneIfMounted(c2[i]) : normalizeVNode(c2[i]);
				if (isSameVNodeType(n1, n2)) patch(n1, n2, container, null, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
				else break;
				i++;
			}
			while (i <= e1 && i <= e2) {
				const n1 = c1[e1];
				const n2 = c2[e2] = optimized ? cloneIfMounted(c2[e2]) : normalizeVNode(c2[e2]);
				if (isSameVNodeType(n1, n2)) patch(n1, n2, container, null, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
				else break;
				e1--;
				e2--;
			}
			if (i > e1) {
				if (i <= e2) {
					const nextPos = e2 + 1;
					const anchor = nextPos < l2 ? c2[nextPos].el : parentAnchor;
					while (i <= e2) {
						patch(null, c2[i] = optimized ? cloneIfMounted(c2[i]) : normalizeVNode(c2[i]), container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
						i++;
					}
				}
			} else if (i > e2) while (i <= e1) {
				unmount(c1[i], parentComponent, parentSuspense, true);
				i++;
			}
			else {
				const s1 = i;
				const s2 = i;
				const keyToNewIndexMap = /* @__PURE__ */ new Map();
				for (i = s2; i <= e2; i++) {
					const nextChild = c2[i] = optimized ? cloneIfMounted(c2[i]) : normalizeVNode(c2[i]);
					if (nextChild.key != null) keyToNewIndexMap.set(nextChild.key, i);
				}
				let j;
				let patched = 0;
				const toBePatched = e2 - s2 + 1;
				let moved = false;
				let maxNewIndexSoFar = 0;
				const newIndexToOldIndexMap = new Array(toBePatched);
				for (i = 0; i < toBePatched; i++) newIndexToOldIndexMap[i] = 0;
				for (i = s1; i <= e1; i++) {
					const prevChild = c1[i];
					if (patched >= toBePatched) {
						unmount(prevChild, parentComponent, parentSuspense, true);
						continue;
					}
					let newIndex;
					if (prevChild.key != null) newIndex = keyToNewIndexMap.get(prevChild.key);
					else for (j = s2; j <= e2; j++) if (newIndexToOldIndexMap[j - s2] === 0 && isSameVNodeType(prevChild, c2[j])) {
						newIndex = j;
						break;
					}
					if (newIndex === void 0) unmount(prevChild, parentComponent, parentSuspense, true);
					else {
						newIndexToOldIndexMap[newIndex - s2] = i + 1;
						if (newIndex >= maxNewIndexSoFar) maxNewIndexSoFar = newIndex;
						else moved = true;
						patch(prevChild, c2[newIndex], container, null, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
						patched++;
					}
				}
				const increasingNewIndexSequence = moved ? getSequence(newIndexToOldIndexMap) : EMPTY_ARR;
				j = increasingNewIndexSequence.length - 1;
				for (i = toBePatched - 1; i >= 0; i--) {
					const nextIndex = s2 + i;
					const nextChild = c2[nextIndex];
					const anchorVNode = c2[nextIndex + 1];
					const anchor = nextIndex + 1 < l2 ? anchorVNode.el || resolveAsyncComponentPlaceholder(anchorVNode) : parentAnchor;
					if (newIndexToOldIndexMap[i] === 0) patch(null, nextChild, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized);
					else if (moved) {
						if (j < 0 || i !== increasingNewIndexSequence[j]) move(nextChild, container, anchor, 2);
						else j--;
					}
				}
			}
		};
		const move = (vnode, container, anchor, moveType, parentSuspense = null) => {
			const { el, type, transition, children, shapeFlag } = vnode;
			if (shapeFlag & 6) {
				move(vnode.component.subTree, container, anchor, moveType);
				return;
			}
			if (shapeFlag & 128) {
				vnode.suspense.move(container, anchor, moveType);
				return;
			}
			if (shapeFlag & 64) {
				type.move(vnode, container, anchor, internals);
				return;
			}
			if (type === Fragment) {
				hostInsert(el, container, anchor);
				for (let i = 0; i < children.length; i++) move(children[i], container, anchor, moveType);
				hostInsert(vnode.anchor, container, anchor);
				return;
			}
			if (type === Static) {
				moveStaticNode(vnode, container, anchor);
				return;
			}
			if (moveType !== 2 && shapeFlag & 1 && transition) {
				if (moveType === 0) {
					if (transition.persisted && !el[leaveCbKey]) hostInsert(el, container, anchor);
					else {
						transition.beforeEnter(el);
						hostInsert(el, container, anchor);
						queuePostRenderEffect(() => transition.enter(el), parentSuspense);
					}
				} else {
					const { leave, delayLeave, afterLeave } = transition;
					const remove2 = () => {
						if (vnode.ctx.isUnmounted) hostRemove(el);
						else hostInsert(el, container, anchor);
					};
					const performLeave = () => {
						const wasLeaving = el._isLeaving || !!el[leaveCbKey];
						if (el._isLeaving) el[leaveCbKey](true);
						if (transition.persisted && !wasLeaving) remove2();
						else leave(el, () => {
							remove2();
							afterLeave && afterLeave();
						});
					};
					if (delayLeave) delayLeave(el, remove2, performLeave);
					else performLeave();
				}
			} else hostInsert(el, container, anchor);
		};
		const unmount = (vnode, parentComponent, parentSuspense, doRemove = false, optimized = false) => {
			const { type, props, ref, children, dynamicChildren, shapeFlag, patchFlag, dirs, cacheIndex, memo } = vnode;
			if (patchFlag === -2) optimized = false;
			if (ref != null) {
				pauseTracking();
				setRef(ref, null, parentSuspense, vnode, true);
				resetTracking();
			}
			if (cacheIndex != null) parentComponent.renderCache[cacheIndex] = void 0;
			if (shapeFlag & 256) {
				parentComponent.ctx.deactivate(vnode);
				return;
			}
			const shouldInvokeDirs = shapeFlag & 1 && dirs;
			const shouldInvokeVnodeHook = !isAsyncWrapper(vnode);
			let vnodeHook;
			if (shouldInvokeVnodeHook && (vnodeHook = props && props.onVnodeBeforeUnmount)) invokeVNodeHook(vnodeHook, parentComponent, vnode);
			if (shapeFlag & 6) unmountComponent(vnode.component, parentSuspense, doRemove);
			else {
				if (shapeFlag & 128) {
					vnode.suspense.unmount(parentSuspense, doRemove);
					return;
				}
				if (shouldInvokeDirs) invokeDirectiveHook(vnode, null, parentComponent, "beforeUnmount");
				if (shapeFlag & 64) vnode.type.remove(vnode, parentComponent, parentSuspense, internals, doRemove);
				else if (dynamicChildren && !dynamicChildren.hasOnce && (type !== Fragment || patchFlag > 0 && patchFlag & 64)) unmountChildren(dynamicChildren, parentComponent, parentSuspense, false, true);
				else if (type === Fragment && patchFlag & 384 || !optimized && shapeFlag & 16) unmountChildren(children, parentComponent, parentSuspense);
				if (doRemove) remove(vnode);
			}
			const shouldInvalidateMemo = memo != null && cacheIndex == null;
			if (shouldInvokeVnodeHook && (vnodeHook = props && props.onVnodeUnmounted) || shouldInvokeDirs || shouldInvalidateMemo) queuePostRenderEffect(() => {
				vnodeHook && invokeVNodeHook(vnodeHook, parentComponent, vnode);
				shouldInvokeDirs && invokeDirectiveHook(vnode, null, parentComponent, "unmounted");
				if (shouldInvalidateMemo) vnode.el = null;
			}, parentSuspense);
		};
		const remove = (vnode) => {
			const { type, el, anchor, transition } = vnode;
			if (type === Fragment) {
				removeFragment(el, anchor);
				return;
			}
			if (type === Static) {
				removeStaticNode(vnode);
				return;
			}
			const performRemove = () => {
				hostRemove(el);
				if (transition && !transition.persisted && transition.afterLeave) transition.afterLeave();
			};
			if (vnode.shapeFlag & 1 && transition && !transition.persisted) {
				const { leave, delayLeave } = transition;
				const performLeave = () => leave(el, performRemove);
				if (delayLeave) delayLeave(vnode.el, performRemove, performLeave);
				else performLeave();
			} else performRemove();
		};
		const removeFragment = (cur, end) => {
			let next;
			while (cur !== end) {
				next = hostNextSibling(cur);
				hostRemove(cur);
				cur = next;
			}
			hostRemove(end);
		};
		const unmountComponent = (instance, parentSuspense, doRemove) => {
			const { bum, scope, job, subTree, um, m, a } = instance;
			invalidateMount(m);
			invalidateMount(a);
			if (bum) invokeArrayFns(bum);
			scope.stop();
			if (job) {
				job.flags |= 8;
				unmount(subTree, instance, parentSuspense, doRemove);
			}
			if (um) queuePostRenderEffect(um, parentSuspense);
			queuePostRenderEffect(() => {
				instance.isUnmounted = true;
			}, parentSuspense);
		};
		const unmountChildren = (children, parentComponent, parentSuspense, doRemove = false, optimized = false, start = 0) => {
			for (let i = start; i < children.length; i++) unmount(children[i], parentComponent, parentSuspense, doRemove, optimized);
		};
		const getNextHostNode = (vnode) => {
			if (vnode.shapeFlag & 6) return getNextHostNode(vnode.component.subTree);
			if (vnode.shapeFlag & 128) return vnode.suspense.next();
			const el = hostNextSibling(vnode.anchor || vnode.el);
			const teleportEnd = el && el[TeleportEndKey];
			return teleportEnd ? hostNextSibling(teleportEnd) : el;
		};
		let isFlushing = false;
		const render = (vnode, container, namespace) => {
			let instance;
			if (vnode == null) {
				if (container._vnode) {
					unmount(container._vnode, null, null, true);
					instance = container._vnode.component;
				}
			} else patch(container._vnode || null, vnode, container, null, null, null, namespace);
			container._vnode = vnode;
			if (!isFlushing) {
				isFlushing = true;
				flushPreFlushCbs(instance);
				flushPostFlushCbs();
				isFlushing = false;
			}
		};
		const internals = {
			p: patch,
			um: unmount,
			m: move,
			r: remove,
			mt: mountComponent,
			mc: mountChildren,
			pc: patchChildren,
			pbc: patchBlockChildren,
			n: getNextHostNode,
			o: options
		};
		let hydrate;
		let hydrateNode;
		if (createHydrationFns) [hydrate, hydrateNode] = createHydrationFns(internals);
		return {
			render,
			hydrate,
			createApp: createAppAPI(render, hydrate)
		};
	}
	function resolveChildrenNamespace({ type, props }, currentNamespace) {
		return currentNamespace === "svg" && type === "foreignObject" || currentNamespace === "mathml" && type === "annotation-xml" && props && props.encoding && props.encoding.includes("html") ? void 0 : currentNamespace;
	}
	function toggleRecurse({ effect, job }, allowed) {
		if (allowed) {
			effect.flags |= 32;
			job.flags |= 4;
		} else {
			effect.flags &= -33;
			job.flags &= -5;
		}
	}
	function needTransition(parentSuspense, transition) {
		return (!parentSuspense || parentSuspense && !parentSuspense.pendingBranch) && transition && !transition.persisted;
	}
	function traverseStaticChildren(n1, n2, shallow = false) {
		const ch1 = n1.children;
		const ch2 = n2.children;
		if (isArray$1(ch1) && isArray$1(ch2)) for (let i = 0; i < ch1.length; i++) {
			const c1 = ch1[i];
			let c2 = ch2[i];
			if (c2.shapeFlag & 1 && !c2.dynamicChildren) {
				if (c2.patchFlag <= 0 || c2.patchFlag === 32) {
					c2 = ch2[i] = cloneIfMounted(ch2[i]);
					c2.el = c1.el;
				}
				if (!shallow && c2.patchFlag !== -2) traverseStaticChildren(c1, c2);
			}
			if (c2.type === Text) {
				if (c2.patchFlag === -1) c2 = ch2[i] = cloneIfMounted(c2);
				c2.el = c1.el;
			}
			if (c2.type === Comment && !c2.el) c2.el = c1.el;
		}
	}
	function getSequence(arr) {
		const p = arr.slice();
		const result = [0];
		let i, j, u, v, c;
		const len = arr.length;
		for (i = 0; i < len; i++) {
			const arrI = arr[i];
			if (arrI !== 0) {
				j = result[result.length - 1];
				if (arr[j] < arrI) {
					p[i] = j;
					result.push(i);
					continue;
				}
				u = 0;
				v = result.length - 1;
				while (u < v) {
					c = u + v >> 1;
					if (arr[result[c]] < arrI) u = c + 1;
					else v = c;
				}
				if (arrI < arr[result[u]]) {
					if (u > 0) p[i] = result[u - 1];
					result[u] = i;
				}
			}
		}
		u = result.length;
		v = result[u - 1];
		while (u-- > 0) {
			result[u] = v;
			v = p[v];
		}
		return result;
	}
	function locateNonHydratedAsyncRoot(instance) {
		const subComponent = instance.subTree.component;
		if (subComponent) {
			if (subComponent.asyncDep && !subComponent.asyncResolved) return subComponent;
			else return locateNonHydratedAsyncRoot(subComponent);
		}
	}
	function invalidateMount(hooks) {
		if (hooks) for (let i = 0; i < hooks.length; i++) hooks[i].flags |= 8;
	}
	function resolveAsyncComponentPlaceholder(anchorVnode) {
		if (anchorVnode.placeholder) return anchorVnode.placeholder;
		const instance = anchorVnode.component;
		if (instance) return resolveAsyncComponentPlaceholder(instance.subTree);
		return null;
	}
	var isSuspense = (type) => type.__isSuspense;
	function queueEffectWithSuspense(fn, suspense) {
		if (suspense && suspense.pendingBranch) {
			if (isArray$1(fn)) suspense.effects.push(...fn);
			else suspense.effects.push(fn);
		} else queuePostFlushCb(fn);
	}
	var Fragment = /* @__PURE__ */ Symbol.for("v-fgt");
	var Text = /* @__PURE__ */ Symbol.for("v-txt");
	var Comment = /* @__PURE__ */ Symbol.for("v-cmt");
	var Static = /* @__PURE__ */ Symbol.for("v-stc");
	var blockStack = [];
	var currentBlock = null;
	function openBlock(disableTracking = false) {
		blockStack.push(currentBlock = disableTracking ? null : []);
	}
	function closeBlock() {
		blockStack.pop();
		currentBlock = blockStack[blockStack.length - 1] || null;
	}
	var isBlockTreeEnabled = 1;
	function setBlockTracking(value, inVOnce = false) {
		isBlockTreeEnabled += value;
		if (value < 0 && currentBlock && inVOnce) currentBlock.hasOnce = true;
	}
	function setupBlock(vnode) {
		vnode.dynamicChildren = isBlockTreeEnabled > 0 ? currentBlock || EMPTY_ARR : null;
		closeBlock();
		if (isBlockTreeEnabled > 0 && currentBlock) currentBlock.push(vnode);
		return vnode;
	}
	function createElementBlock(type, props, children, patchFlag, dynamicProps, shapeFlag) {
		return setupBlock(createBaseVNode(type, props, children, patchFlag, dynamicProps, shapeFlag, true));
	}
	function createBlock(type, props, children, patchFlag, dynamicProps) {
		return setupBlock(createVNode(type, props, children, patchFlag, dynamicProps, true));
	}
	function isVNode(value) {
		return value ? value.__v_isVNode === true : false;
	}
	function isSameVNodeType(n1, n2) {
		return n1.type === n2.type && n1.key === n2.key;
	}
	var normalizeKey = ({ key }) => key != null ? key : null;
	var normalizeRef = ({ ref, ref_key, ref_for }) => {
		if (typeof ref === "number") ref = "" + ref;
		return ref != null ? isString(ref) || /* @__PURE__ */ isRef(ref) || isFunction$1(ref) ? {
			i: currentRenderingInstance,
			r: ref,
			k: ref_key,
			f: !!ref_for
		} : ref : null;
	};
	function createBaseVNode(type, props = null, children = null, patchFlag = 0, dynamicProps = null, shapeFlag = type === Fragment ? 0 : 1, isBlockNode = false, needFullChildrenNormalization = false) {
		const vnode = {
			__v_isVNode: true,
			__v_skip: true,
			type,
			props,
			key: props && normalizeKey(props),
			ref: props && normalizeRef(props),
			scopeId: currentScopeId,
			slotScopeIds: null,
			children,
			component: null,
			suspense: null,
			ssContent: null,
			ssFallback: null,
			dirs: null,
			transition: null,
			el: null,
			anchor: null,
			target: null,
			targetStart: null,
			targetAnchor: null,
			staticCount: 0,
			shapeFlag,
			patchFlag,
			dynamicProps,
			dynamicChildren: null,
			appContext: null,
			ctx: currentRenderingInstance
		};
		if (needFullChildrenNormalization) {
			normalizeChildren(vnode, children);
			if (shapeFlag & 128) type.normalize(vnode);
		} else if (children) vnode.shapeFlag |= isString(children) ? 8 : 16;
		if (isBlockTreeEnabled > 0 && !isBlockNode && currentBlock && (vnode.patchFlag > 0 || shapeFlag & 6) && vnode.patchFlag !== 32) currentBlock.push(vnode);
		return vnode;
	}
	var createVNode = _createVNode;
	function _createVNode(type, props = null, children = null, patchFlag = 0, dynamicProps = null, isBlockNode = false) {
		if (!type || type === NULL_DYNAMIC_COMPONENT) type = Comment;
		if (isVNode(type)) {
			const cloned = cloneVNode(type, props, true);
			if (children) normalizeChildren(cloned, children);
			if (isBlockTreeEnabled > 0 && !isBlockNode && currentBlock) {
				if (cloned.shapeFlag & 6) currentBlock[currentBlock.indexOf(type)] = cloned;
				else currentBlock.push(cloned);
			}
			cloned.patchFlag = -2;
			return cloned;
		}
		if (isClassComponent(type)) type = type.__vccOpts;
		if (props) {
			props = guardReactiveProps(props);
			let { class: klass, style } = props;
			if (klass && !isString(klass)) props.class = normalizeClass(klass);
			if (isObject(style)) {
				if (/* @__PURE__ */ isProxy(style) && !isArray$1(style)) style = extend({}, style);
				props.style = normalizeStyle(style);
			}
		}
		const shapeFlag = isString(type) ? 1 : isSuspense(type) ? 128 : isTeleport(type) ? 64 : isObject(type) ? 4 : isFunction$1(type) ? 2 : 0;
		return createBaseVNode(type, props, children, patchFlag, dynamicProps, shapeFlag, isBlockNode, true);
	}
	function guardReactiveProps(props) {
		if (!props) return null;
		return /* @__PURE__ */ isProxy(props) || isInternalObject(props) ? extend({}, props) : props;
	}
	function cloneVNode(vnode, extraProps, mergeRef = false, cloneTransition = false) {
		const { props, ref, patchFlag, children, transition } = vnode;
		const mergedProps = extraProps ? mergeProps(props || {}, extraProps) : props;
		const cloned = {
			__v_isVNode: true,
			__v_skip: true,
			type: vnode.type,
			props: mergedProps,
			key: mergedProps && normalizeKey(mergedProps),
			ref: extraProps && extraProps.ref ? mergeRef && ref ? isArray$1(ref) ? ref.concat(normalizeRef(extraProps)) : [ref, normalizeRef(extraProps)] : normalizeRef(extraProps) : ref,
			scopeId: vnode.scopeId,
			slotScopeIds: vnode.slotScopeIds,
			children,
			target: vnode.target,
			targetStart: vnode.targetStart,
			targetAnchor: vnode.targetAnchor,
			staticCount: vnode.staticCount,
			shapeFlag: vnode.shapeFlag,
			patchFlag: extraProps && vnode.type !== Fragment ? patchFlag === -1 ? 16 : patchFlag | 16 : patchFlag,
			dynamicProps: vnode.dynamicProps,
			dynamicChildren: vnode.dynamicChildren,
			appContext: vnode.appContext,
			dirs: vnode.dirs,
			transition,
			component: vnode.component,
			suspense: vnode.suspense,
			ssContent: vnode.ssContent && cloneVNode(vnode.ssContent),
			ssFallback: vnode.ssFallback && cloneVNode(vnode.ssFallback),
			placeholder: vnode.placeholder,
			el: vnode.el,
			anchor: vnode.anchor,
			ctx: vnode.ctx,
			ce: vnode.ce
		};
		if (transition && cloneTransition) setTransitionHooks(cloned, transition.clone(cloned));
		return cloned;
	}
	function createTextVNode(text = " ", flag = 0) {
		return createVNode(Text, null, text, flag);
	}
	function createStaticVNode(content, numberOfNodes) {
		const vnode = createVNode(Static, null, content);
		vnode.staticCount = numberOfNodes;
		return vnode;
	}
	function createCommentVNode(text = "", asBlock = false) {
		return asBlock ? (openBlock(), createBlock(Comment, null, text)) : createVNode(Comment, null, text);
	}
	function normalizeVNode(child) {
		if (child == null || typeof child === "boolean") return createVNode(Comment);
		else if (isArray$1(child)) return createVNode(Fragment, null, child.slice());
		else if (isVNode(child)) return cloneIfMounted(child);
		else return createVNode(Text, null, String(child));
	}
	function cloneIfMounted(child) {
		return child.el === null && child.patchFlag !== -1 || child.memo ? child : cloneVNode(child);
	}
	function normalizeChildren(vnode, children) {
		let type = 0;
		const { shapeFlag } = vnode;
		if (children == null) children = null;
		else if (isArray$1(children)) type = 16;
		else if (typeof children === "object") {
			if (shapeFlag & 65) {
				const slot = children.default;
				if (slot) {
					slot._c && (slot._d = false);
					normalizeChildren(vnode, slot());
					slot._c && (slot._d = true);
				}
				return;
			} else {
				type = 32;
				const slotFlag = children._;
				if (!slotFlag && !isInternalObject(children)) children._ctx = currentRenderingInstance;
				else if (slotFlag === 3 && currentRenderingInstance) {
					if (currentRenderingInstance.slots._ === 1) children._ = 1;
					else {
						children._ = 2;
						vnode.patchFlag |= 1024;
					}
				}
			}
		} else if (isFunction$1(children)) {
			if (shapeFlag & 65) {
				normalizeChildren(vnode, { default: children });
				return;
			}
			children = {
				default: children,
				_ctx: currentRenderingInstance
			};
			type = 32;
		} else {
			children = String(children);
			if (shapeFlag & 64) {
				type = 16;
				children = [createTextVNode(children)];
			} else type = 8;
		}
		vnode.children = children;
		vnode.shapeFlag |= type;
	}
	function mergeProps(...args) {
		const ret = {};
		for (let i = 0; i < args.length; i++) {
			const toMerge = args[i];
			for (const key in toMerge) if (key === "class") {
				if (ret.class !== toMerge.class) ret.class = normalizeClass([ret.class, toMerge.class]);
			} else if (key === "style") ret.style = normalizeStyle([ret.style, toMerge.style]);
			else if (isOn(key)) {
				const existing = ret[key];
				const incoming = toMerge[key];
				if (incoming && existing !== incoming && !(isArray$1(existing) && existing.includes(incoming))) ret[key] = existing ? [].concat(existing, incoming) : incoming;
				else if (incoming == null && existing == null && !isModelListener(key)) ret[key] = incoming;
			} else if (key !== "") ret[key] = toMerge[key];
		}
		return ret;
	}
	function invokeVNodeHook(hook, instance, vnode, prevVNode = null) {
		callWithAsyncErrorHandling(hook, instance, 7, [vnode, prevVNode]);
	}
	var emptyAppContext = createAppContext();
	var uid = 0;
	function createComponentInstance(vnode, parent, suspense) {
		const type = vnode.type;
		const appContext = (parent ? parent.appContext : vnode.appContext) || emptyAppContext;
		const instance = {
			uid: uid++,
			vnode,
			type,
			parent,
			appContext,
			root: null,
			next: null,
			subTree: null,
			effect: null,
			update: null,
			job: null,
			scope: new EffectScope(true),
			render: null,
			proxy: null,
			exposed: null,
			exposeProxy: null,
			withProxy: null,
			provides: parent ? parent.provides : Object.create(appContext.provides),
			ids: parent ? parent.ids : [
				"",
				0,
				0
			],
			accessCache: null,
			renderCache: [],
			components: null,
			directives: null,
			propsOptions: normalizePropsOptions(type, appContext),
			emitsOptions: normalizeEmitsOptions(type, appContext),
			emit: null,
			emitted: null,
			propsDefaults: EMPTY_OBJ,
			inheritAttrs: type.inheritAttrs,
			ctx: EMPTY_OBJ,
			data: EMPTY_OBJ,
			props: EMPTY_OBJ,
			attrs: EMPTY_OBJ,
			slots: EMPTY_OBJ,
			refs: EMPTY_OBJ,
			setupState: EMPTY_OBJ,
			setupContext: null,
			suspense,
			suspenseId: suspense ? suspense.pendingId : 0,
			asyncDep: null,
			asyncResolved: false,
			isMounted: false,
			isUnmounted: false,
			isDeactivated: false,
			bc: null,
			c: null,
			bm: null,
			m: null,
			bu: null,
			u: null,
			um: null,
			bum: null,
			da: null,
			a: null,
			rtg: null,
			rtc: null,
			ec: null,
			sp: null
		};
		instance.ctx = { _: instance };
		instance.root = parent ? parent.root : instance;
		instance.emit = emit.bind(null, instance);
		if (vnode.ce) vnode.ce(instance);
		return instance;
	}
	var currentInstance = null;
	var getCurrentInstance = () => currentInstance || currentRenderingInstance;
	var internalSetCurrentInstance;
	var setInSSRSetupState;
	{
		const g = getGlobalThis();
		const registerGlobalSetter = (key, setter) => {
			let setters;
			if (!(setters = g[key])) setters = g[key] = [];
			setters.push(setter);
			return (v) => {
				if (setters.length > 1) setters.forEach((set) => set(v));
				else setters[0](v);
			};
		};
		internalSetCurrentInstance = registerGlobalSetter(`__VUE_INSTANCE_SETTERS__`, (v) => currentInstance = v);
		setInSSRSetupState = registerGlobalSetter(`__VUE_SSR_SETTERS__`, (v) => isInSSRComponentSetup = v);
	}
	var setCurrentInstance = (instance) => {
		const prev = currentInstance;
		internalSetCurrentInstance(instance);
		instance.scope.on();
		return () => {
			instance.scope.off();
			internalSetCurrentInstance(prev);
		};
	};
	var unsetCurrentInstance = () => {
		currentInstance && currentInstance.scope.off();
		internalSetCurrentInstance(null);
	};
	function isStatefulComponent(instance) {
		return instance.vnode.shapeFlag & 4;
	}
	var isInSSRComponentSetup = false;
	function setupComponent(instance, isSSR = false, optimized = false) {
		isSSR && setInSSRSetupState(isSSR);
		const { props, children } = instance.vnode;
		const isStateful = isStatefulComponent(instance);
		initProps(instance, props, isStateful, isSSR);
		initSlots(instance, children, optimized || isSSR);
		const setupResult = isStateful ? setupStatefulComponent(instance, isSSR) : void 0;
		isSSR && setInSSRSetupState(false);
		return setupResult;
	}
	function setupStatefulComponent(instance, isSSR) {
		const Component = instance.type;
		instance.accessCache = /* @__PURE__ */ Object.create(null);
		instance.proxy = new Proxy(instance.ctx, PublicInstanceProxyHandlers);
		const { setup } = Component;
		if (setup) {
			pauseTracking();
			const setupContext = instance.setupContext = setup.length > 1 ? createSetupContext(instance) : null;
			const reset = setCurrentInstance(instance);
			const setupResult = callWithErrorHandling(setup, instance, 0, [instance.props, setupContext]);
			const isAsyncSetup = isPromise(setupResult);
			resetTracking();
			reset();
			if ((isAsyncSetup || instance.sp) && !isAsyncWrapper(instance)) markAsyncBoundary(instance);
			if (isAsyncSetup) {
				setupResult.then(unsetCurrentInstance, unsetCurrentInstance);
				if (isSSR) return setupResult.then((resolvedResult) => {
					setInSSRSetupState(true);
					try {
						handleSetupResult(instance, resolvedResult, isSSR);
					} finally {
						setInSSRSetupState(false);
					}
				}).catch((e) => {
					handleError(e, instance, 0);
				});
				else instance.asyncDep = setupResult;
			} else handleSetupResult(instance, setupResult, isSSR);
		} else finishComponentSetup(instance, isSSR);
	}
	function handleSetupResult(instance, setupResult, isSSR) {
		if (isFunction$1(setupResult)) {
			if (instance.type.__ssrInlineRender) instance.ssrRender = setupResult;
			else instance.render = setupResult;
		} else if (isObject(setupResult)) instance.setupState = proxyRefs(setupResult);
		finishComponentSetup(instance, isSSR);
	}
	var compile;
	var installWithProxy;
	function finishComponentSetup(instance, isSSR, skipOptions) {
		const Component = instance.type;
		if (!instance.render) {
			if (!isSSR && compile && !Component.render) {
				const template = Component.template || resolveMergedOptions(instance).template;
				if (template) {
					const { isCustomElement, compilerOptions } = instance.appContext.config;
					const { delimiters, compilerOptions: componentCompilerOptions } = Component;
					Component.render = compile(template, extend(extend({
						isCustomElement,
						delimiters
					}, compilerOptions), componentCompilerOptions));
				}
			}
			instance.render = Component.render || NOOP;
			if (installWithProxy) installWithProxy(instance);
		}
		{
			const reset = setCurrentInstance(instance);
			pauseTracking();
			try {
				applyOptions(instance);
			} finally {
				resetTracking();
				reset();
			}
		}
	}
	var attrsProxyHandlers = { get(target, key) {
		track(target, "get", "");
		return target[key];
	} };
	function createSetupContext(instance) {
		const expose = (exposed) => {
			instance.exposed = exposed || {};
		};
		return {
			attrs: new Proxy(instance.attrs, attrsProxyHandlers),
			slots: instance.slots,
			emit: instance.emit,
			expose
		};
	}
	function getComponentPublicInstance(instance) {
		if (instance.exposed) return instance.exposeProxy || (instance.exposeProxy = new Proxy(proxyRefs(markRaw(instance.exposed)), {
			get(target, key) {
				if (key in target) return target[key];
				else if (key in publicPropertiesMap) return publicPropertiesMap[key](instance);
			},
			has(target, key) {
				return key in target || key in publicPropertiesMap;
			}
		}));
		else return instance.proxy;
	}
	function isClassComponent(value) {
		return isFunction$1(value) && "__vccOpts" in value;
	}
	var computed = (getterOrOptions, debugOptions) => {
		return /* @__PURE__ */ computed$1(getterOrOptions, debugOptions, isInSSRComponentSetup);
	};
	function h(type, propsOrChildren, children) {
		try {
			setBlockTracking(-1);
			const l = arguments.length;
			if (l === 2) {
				if (isObject(propsOrChildren) && !isArray$1(propsOrChildren)) {
					if (isVNode(propsOrChildren)) return createVNode(type, null, [propsOrChildren]);
					return createVNode(type, propsOrChildren);
				} else return createVNode(type, null, propsOrChildren);
			} else {
				if (l > 3) children = Array.prototype.slice.call(arguments, 2);
				else if (l === 3 && isVNode(children)) children = [children];
				return createVNode(type, propsOrChildren, children);
			}
		} finally {
			setBlockTracking(1);
		}
	}
	var version = "3.5.41";
	//#endregion
	//#region node_modules/@vue/runtime-dom/dist/runtime-dom.esm-bundler.js
	/**
	* @vue/runtime-dom v3.5.41
	* (c) 2018-present Yuxi (Evan) You and Vue contributors
	* @license MIT
	**/
	var policy = void 0;
	var tt = typeof window !== "undefined" && window.trustedTypes;
	if (tt) try {
		policy = /* @__PURE__ */ tt.createPolicy("vue", { createHTML: (val) => val });
	} catch (e) {}
	var unsafeToTrustedHTML = policy ? (val) => policy.createHTML(val) : (val) => val;
	var svgNS = "http://www.w3.org/2000/svg";
	var mathmlNS = "http://www.w3.org/1998/Math/MathML";
	var doc = typeof document !== "undefined" ? document : null;
	var templateContainer = doc && /* @__PURE__ */ doc.createElement("template");
	var nodeOps = {
		insert: (child, parent, anchor) => {
			parent.insertBefore(child, anchor || null);
		},
		remove: (child) => {
			const parent = child.parentNode;
			if (parent) parent.removeChild(child);
		},
		createElement: (tag, namespace, is, props) => {
			const el = namespace === "svg" ? doc.createElementNS(svgNS, tag) : namespace === "mathml" ? doc.createElementNS(mathmlNS, tag) : is ? doc.createElement(tag, { is }) : doc.createElement(tag);
			if (tag === "select" && props && props.multiple != null) el.setAttribute("multiple", props.multiple);
			return el;
		},
		createText: (text) => doc.createTextNode(text),
		createComment: (text) => doc.createComment(text),
		setText: (node, text) => {
			node.nodeValue = text;
		},
		setElementText: (el, text) => {
			el.textContent = text;
		},
		parentNode: (node) => node.parentNode,
		nextSibling: (node) => node.nextSibling,
		querySelector: (selector) => doc.querySelector(selector),
		setScopeId(el, id) {
			el.setAttribute(id, "");
		},
		insertStaticContent(content, parent, anchor, namespace, start, end) {
			const before = anchor ? anchor.previousSibling : parent.lastChild;
			if (start && (start === end || start.nextSibling)) while (true) {
				parent.insertBefore(start.cloneNode(true), anchor);
				if (start === end || !(start = start.nextSibling)) break;
			}
			else {
				templateContainer.innerHTML = unsafeToTrustedHTML(namespace === "svg" ? `<svg>${content}</svg>` : namespace === "mathml" ? `<math>${content}</math>` : content);
				const template = templateContainer.content;
				if (namespace === "svg" || namespace === "mathml") {
					const wrapper = template.firstChild;
					while (wrapper.firstChild) template.appendChild(wrapper.firstChild);
					template.removeChild(wrapper);
				}
				parent.insertBefore(template, anchor);
			}
			return [before ? before.nextSibling : parent.firstChild, anchor ? anchor.previousSibling : parent.lastChild];
		}
	};
	var vtcKey = /* @__PURE__ */ Symbol("_vtc");
	function patchClass(el, value, isSVG) {
		const transitionClasses = el[vtcKey];
		if (transitionClasses) value = (value ? [value, ...transitionClasses] : [...transitionClasses]).join(" ");
		if (value == null) el.removeAttribute("class");
		else if (isSVG) el.setAttribute("class", value);
		else el.className = value;
	}
	var vShowOriginalDisplay = /* @__PURE__ */ Symbol("_vod");
	var vShowHidden = /* @__PURE__ */ Symbol("_vsh");
	var CSS_VAR_TEXT = /* @__PURE__ */ Symbol("");
	var displayRE = /(?:^|;)\s*display\s*:/;
	function patchStyle(el, prev, next) {
		const style = el.style;
		const isCssString = isString(next);
		let hasControlledDisplay = false;
		if (next && !isCssString) {
			if (prev) {
				if (!isString(prev)) {
					for (const key in prev) if (next[key] == null) setStyle(style, key, "");
				} else for (const prevStyle of prev.split(";")) {
					const key = prevStyle.slice(0, prevStyle.indexOf(":")).trim();
					if (next[key] == null) setStyle(style, key, "");
				}
			}
			for (const key in next) {
				if (key === "display") hasControlledDisplay = true;
				const value = next[key];
				if (value != null) {
					if (!shouldPreserveTextareaResizeStyle(el, key, !isString(prev) && prev ? prev[key] : void 0, value)) setStyle(style, key, value);
				} else setStyle(style, key, "");
			}
		} else if (isCssString) {
			if (prev !== next) {
				const cssVarText = style[CSS_VAR_TEXT];
				if (cssVarText) next += ";" + cssVarText;
				style.cssText = next;
				hasControlledDisplay = displayRE.test(next);
			}
		} else if (prev) el.removeAttribute("style");
		if (vShowOriginalDisplay in el) {
			el[vShowOriginalDisplay] = hasControlledDisplay ? style.display : "";
			if (el[vShowHidden]) style.display = "none";
		}
	}
	var importantRE = /\s*!important$/;
	function setStyle(style, name, val) {
		if (isArray$1(val)) val.forEach((v) => setStyle(style, name, v));
		else {
			if (val == null) val = "";
			if (name.startsWith("--")) style.setProperty(name, val);
			else {
				const prefixed = autoPrefix(style, name);
				if (importantRE.test(val)) style.setProperty(hyphenate(prefixed), val.replace(importantRE, ""), "important");
				else style[prefixed] = val;
			}
		}
	}
	var prefixes = [
		"Webkit",
		"Moz",
		"ms"
	];
	var prefixCache = {};
	function autoPrefix(style, rawName) {
		const cached = prefixCache[rawName];
		if (cached) return cached;
		let name = camelize(rawName);
		if (name !== "filter" && name in style) return prefixCache[rawName] = name;
		name = capitalize(name);
		for (let i = 0; i < prefixes.length; i++) {
			const prefixed = prefixes[i] + name;
			if (prefixed in style) return prefixCache[rawName] = prefixed;
		}
		return rawName;
	}
	function shouldPreserveTextareaResizeStyle(el, key, prev, next) {
		return el.tagName === "TEXTAREA" && (key === "width" || key === "height") && isString(next) && prev === next;
	}
	var xlinkNS = "http://www.w3.org/1999/xlink";
	function patchAttr(el, key, value, isSVG, instance, isBoolean = isSpecialBooleanAttr(key)) {
		if (isSVG && key.startsWith("xlink:")) {
			if (value == null) el.removeAttributeNS(xlinkNS, key.slice(6, key.length));
			else el.setAttributeNS(xlinkNS, key, value);
		} else if (value == null || isBoolean && !includeBooleanAttr(value)) el.removeAttribute(key);
		else el.setAttribute(key, isBoolean ? "" : isSymbol(value) ? String(value) : value);
	}
	function patchDOMProp(el, key, value, parentComponent, attrName) {
		if (key === "innerHTML" || key === "textContent") {
			if (value != null) el[key] = key === "innerHTML" ? unsafeToTrustedHTML(value) : value;
			return;
		}
		const tag = el.tagName;
		if (key === "value" && tag !== "PROGRESS" && !tag.includes("-")) {
			const oldValue = tag === "OPTION" ? el.getAttribute("value") || "" : el.value;
			const newValue = value == null ? el.type === "checkbox" ? "on" : "" : String(value);
			if (oldValue !== newValue || !("_value" in el)) el.value = newValue;
			if (value == null) el.removeAttribute(key);
			el._value = value;
			return;
		}
		let needRemove = false;
		if (value === "" || value == null) {
			const type = typeof el[key];
			if (type === "boolean") value = includeBooleanAttr(value);
			else if (value == null && type === "string") {
				value = "";
				needRemove = true;
			} else if (type === "number") {
				value = 0;
				needRemove = true;
			}
		}
		try {
			el[key] = value;
		} catch (e) {}
		needRemove && el.removeAttribute(attrName || key);
	}
	function addEventListener(el, event, handler, options) {
		el.addEventListener(event, handler, options);
	}
	function removeEventListener(el, event, handler, options) {
		el.removeEventListener(event, handler, options);
	}
	var veiKey = /* @__PURE__ */ Symbol("_vei");
	function patchEvent(el, rawName, prevValue, nextValue, instance = null) {
		const invokers = el[veiKey] || (el[veiKey] = {});
		const existingInvoker = invokers[rawName];
		if (nextValue && existingInvoker) existingInvoker.value = nextValue;
		else {
			const [name, options] = parseName(rawName);
			if (nextValue) addEventListener(el, name, invokers[rawName] = createInvoker(nextValue, instance), options);
			else if (existingInvoker) {
				removeEventListener(el, name, existingInvoker, options);
				invokers[rawName] = void 0;
			}
		}
	}
	var optionsModifierRE = /(Once|Passive|Capture)$/;
	var optionsModifierEventRE = /^on:?(?:Once|Passive|Capture)$/;
	function parseName(name) {
		let options;
		let m;
		while ((m = name.match(optionsModifierRE)) && !optionsModifierEventRE.test(name)) {
			if (!options) options = {};
			name = name.slice(0, name.length - m[1].length);
			options[m[1].toLowerCase()] = true;
		}
		return [name[2] === ":" ? name.slice(3) : hyphenate(name.slice(2)), options];
	}
	var cachedNow = 0;
	var p = /* @__PURE__ */ Promise.resolve();
	var getNow = () => cachedNow || (p.then(() => cachedNow = 0), cachedNow = Date.now());
	function createInvoker(initialValue, instance) {
		const invoker = (e) => {
			if (!e._vts) e._vts = Date.now();
			else if (e._vts <= invoker.attached) return;
			const value = invoker.value;
			if (isArray$1(value)) {
				const originalStop = e.stopImmediatePropagation;
				e.stopImmediatePropagation = () => {
					originalStop.call(e);
					e._stopped = true;
				};
				const handlers = value.slice();
				const args = [e];
				for (let i = 0; i < handlers.length; i++) {
					if (e._stopped) break;
					const handler = handlers[i];
					if (handler) callWithAsyncErrorHandling(handler, instance, 5, args);
				}
			} else callWithAsyncErrorHandling(value, instance, 5, [e]);
		};
		invoker.value = initialValue;
		invoker.attached = getNow();
		return invoker;
	}
	var isNativeOn = (key) => key.charCodeAt(0) === 111 && key.charCodeAt(1) === 110 && key.charCodeAt(2) > 96 && key.charCodeAt(2) < 123;
	var patchProp = (el, key, prevValue, nextValue, namespace, parentComponent) => {
		const isSVG = namespace === "svg";
		if (key === "class") patchClass(el, nextValue, isSVG);
		else if (key === "style") patchStyle(el, prevValue, nextValue);
		else if (isOn(key)) {
			if (!isModelListener(key)) patchEvent(el, key, prevValue, nextValue, parentComponent);
		} else if (key[0] === "." ? (key = key.slice(1), true) : key[0] === "^" ? (key = key.slice(1), false) : shouldSetAsProp(el, key, nextValue, isSVG)) {
			patchDOMProp(el, key, nextValue);
			if (!el.tagName.includes("-") && (key === "value" || key === "checked" || key === "selected")) patchAttr(el, key, nextValue, isSVG, parentComponent, key !== "value");
		} else if (el._isVueCE && (shouldSetAsPropForVueCE(el, key) || el._def.__asyncLoader && (/[A-Z]/.test(key) || !isString(nextValue)))) patchDOMProp(el, camelize(key), nextValue, parentComponent, key);
		else {
			if (key === "true-value") el._trueValue = nextValue;
			else if (key === "false-value") el._falseValue = nextValue;
			patchAttr(el, key, nextValue, isSVG);
		}
	};
	function shouldSetAsProp(el, key, value, isSVG) {
		if (isSVG) {
			if (key === "innerHTML" || key === "textContent") return true;
			if (key in el && isNativeOn(key) && isFunction$1(value)) return true;
			return false;
		}
		if (key === "spellcheck" || key === "draggable" || key === "translate" || key === "autocorrect") return false;
		if (key === "sandbox" && el.tagName === "IFRAME") return false;
		if (key === "form") return false;
		if (key === "list" && el.tagName === "INPUT") return false;
		if (key === "type" && el.tagName === "TEXTAREA") return false;
		if (key === "width" || key === "height") {
			const tag = el.tagName;
			if (tag === "IMG" || tag === "VIDEO" || tag === "CANVAS" || tag === "SOURCE") return false;
		}
		if (isNativeOn(key) && isString(value)) return false;
		return key in el;
	}
	function shouldSetAsPropForVueCE(el, key) {
		const props = el._def.props;
		if (!props) return false;
		const camelKey = camelize(key);
		return Array.isArray(props) ? props.some((prop) => camelize(prop) === camelKey) : Object.keys(props).some((prop) => camelize(prop) === camelKey);
	}
	var getModelAssigner = (vnode) => {
		const fn = vnode.props["onUpdate:modelValue"] || false;
		return isArray$1(fn) ? (value) => invokeArrayFns(fn, value) : fn;
	};
	function onCompositionStart(e) {
		e.target.composing = true;
	}
	function onCompositionEnd(e) {
		const target = e.target;
		if (target.composing) {
			target.composing = false;
			target.dispatchEvent(new Event("input"));
		}
	}
	var assignKey = /* @__PURE__ */ Symbol("_assign");
	var initialValueKey = /* @__PURE__ */ Symbol("_initialValue");
	function castValue(value, trim, number) {
		if (trim) value = value.trim();
		if (number) value = looseToNumber(value);
		return value;
	}
	var vModelText = {
		created(el, { modifiers: { lazy, trim, number } }, vnode) {
			if (el.parentNode) {
				if (el.type === "text") el[initialValueKey] = el.defaultValue.replace(/[\r\n]/g, "");
				else if (el.type === "textarea") el[initialValueKey] = el.defaultValue.replace(/\r\n?/g, "\n");
			}
			el[assignKey] = getModelAssigner(vnode);
			const castToNumber = number || vnode.props && vnode.props.type === "number";
			addEventListener(el, lazy ? "change" : "input", (e) => {
				if (e.target.composing) return;
				el[assignKey](castValue(el.value, trim, castToNumber));
			});
			if (trim || castToNumber) addEventListener(el, "change", () => {
				el.value = castValue(el.value, trim, castToNumber);
			});
			if (!lazy) {
				addEventListener(el, "compositionstart", onCompositionStart);
				addEventListener(el, "compositionend", onCompositionEnd);
				addEventListener(el, "change", onCompositionEnd);
			}
		},
		mounted(el, { value, modifiers: { trim, number } }) {
			const newValue = value == null ? "" : value;
			const initialValue = el[initialValueKey];
			delete el[initialValueKey];
			if (initialValue !== void 0 && (el.type === "text" || el.type === "textarea") && el.value !== initialValue) el[assignKey](castValue(el.value, trim, number));
			else el.value = newValue;
		},
		beforeUpdate(el, { value, oldValue, modifiers: { lazy, trim, number } }, vnode) {
			el[assignKey] = getModelAssigner(vnode);
			if (el.composing) return;
			const elValue = (number || el.type === "number") && !/^0\d/.test(el.value) ? looseToNumber(el.value) : el.value;
			const newValue = value == null ? "" : value;
			if (elValue === newValue) return;
			const rootNode = el.getRootNode();
			if ((rootNode instanceof Document || rootNode instanceof ShadowRoot) && rootNode.activeElement === el && el.type !== "range") {
				if (lazy && value === oldValue) return;
				if (trim && el.value.trim() === newValue) return;
			}
			el.value = newValue;
		}
	};
	var systemModifiers = [
		"ctrl",
		"shift",
		"alt",
		"meta"
	];
	var modifierGuards = {
		stop: (e) => e.stopPropagation(),
		prevent: (e) => e.preventDefault(),
		self: (e) => e.target !== e.currentTarget,
		ctrl: (e) => !e.ctrlKey,
		shift: (e) => !e.shiftKey,
		alt: (e) => !e.altKey,
		meta: (e) => !e.metaKey,
		left: (e) => "button" in e && e.button !== 0,
		middle: (e) => "button" in e && e.button !== 1,
		right: (e) => "button" in e && e.button !== 2,
		exact: (e, modifiers) => systemModifiers.some((m) => e[`${m}Key`] && !modifiers.includes(m))
	};
	var withModifiers = (fn, modifiers) => {
		if (!fn) return fn;
		const cache = fn._withMods || (fn._withMods = {});
		const cacheKey = modifiers.join(".");
		return cache[cacheKey] || (cache[cacheKey] = ((event, ...args) => {
			for (let i = 0; i < modifiers.length; i++) {
				const guard = modifierGuards[modifiers[i]];
				if (guard && guard(event, modifiers)) return;
			}
			return fn(event, ...args);
		}));
	};
	var rendererOptions = /* @__PURE__ */ extend({ patchProp }, nodeOps);
	var renderer;
	function ensureRenderer() {
		return renderer || (renderer = createRenderer(rendererOptions));
	}
	var createApp = ((...args) => {
		const app = ensureRenderer().createApp(...args);
		const { mount } = app;
		app.mount = (containerOrSelector) => {
			const container = normalizeContainer(containerOrSelector);
			if (!container) return;
			const component = app._component;
			if (!isFunction$1(component) && !component.render && !component.template) component.template = container.innerHTML;
			if (container.nodeType === 1) container.textContent = "";
			const proxy = mount(container, false, resolveRootNamespace(container));
			if (container instanceof Element) {
				container.removeAttribute("v-cloak");
				container.setAttribute("data-v-app", "");
			}
			return proxy;
		};
		return app;
	});
	function resolveRootNamespace(container) {
		if (container instanceof SVGElement) return "svg";
		if (typeof MathMLElement === "function" && container instanceof MathMLElement) return "mathml";
	}
	function normalizeContainer(container) {
		if (isString(container)) return document.querySelector(container);
		return container;
	}
	//#endregion
	//#region node_modules/@tanstack/vue-query/build/modern/utils.js
	var VUE_QUERY_CLIENT = "VUE_QUERY_CLIENT";
	function getClientKey(key) {
		return `${VUE_QUERY_CLIENT}${key ? `:${key}` : ""}`;
	}
	function updateState(state, update) {
		Object.keys(state).forEach((key) => {
			state[key] = update[key];
		});
	}
	function _cloneDeep(value, customize, currentKey = "", currentLevel = 0) {
		if (customize) {
			const result = customize(value, currentKey, currentLevel);
			if (result === void 0 && /* @__PURE__ */ isRef(value)) return result;
			if (result !== void 0) return result;
		}
		if (Array.isArray(value)) return value.map((val, index) => _cloneDeep(val, customize, String(index), currentLevel + 1));
		if (typeof value === "object" && isPlainObject$1(value)) {
			const entries = Object.entries(value).map(([key, val]) => [key, _cloneDeep(val, customize, key, currentLevel + 1)]);
			return Object.fromEntries(entries);
		}
		return value;
	}
	function cloneDeep(value, customize) {
		return _cloneDeep(value, customize);
	}
	function cloneDeepUnref(obj, unrefGetters = false) {
		return cloneDeep(obj, (val, key, level) => {
			if (level === 1 && key === "queryKey") return cloneDeepUnref(val, true);
			if (unrefGetters && isFunction(val)) return cloneDeepUnref(val(), unrefGetters);
			if (/* @__PURE__ */ isRef(val)) return cloneDeepUnref(unref(val), unrefGetters);
		});
	}
	function isPlainObject$1(value) {
		if (Object.prototype.toString.call(value) !== "[object Object]") return false;
		const prototype = Object.getPrototypeOf(value);
		return prototype === null || prototype === Object.prototype;
	}
	function isFunction(value) {
		return typeof value === "function";
	}
	//#endregion
	//#region node_modules/@tanstack/vue-query/build/modern/useQueryClient.js
	function useQueryClient(id = "") {
		if (!hasInjectionContext()) throw new Error("vue-query hooks can only be used inside setup() function or functions that support injection context.");
		const queryClient = inject(getClientKey(id));
		if (!queryClient) throw new Error("No 'queryClient' found in Vue context, use 'VueQueryPlugin' to properly initialize the library.");
		return queryClient;
	}
	//#endregion
	//#region node_modules/@tanstack/vue-query/build/modern/queryCache.js
	var QueryCache = class extends QueryCache$1 {
		find(filters) {
			return super.find(cloneDeepUnref(filters));
		}
		findAll(filters = {}) {
			return super.findAll(cloneDeepUnref(filters));
		}
	};
	//#endregion
	//#region node_modules/@tanstack/vue-query/build/modern/mutationCache.js
	var MutationCache = class extends MutationCache$1 {
		find(filters) {
			return super.find(cloneDeepUnref(filters));
		}
		findAll(filters = {}) {
			return super.findAll(cloneDeepUnref(filters));
		}
	};
	//#endregion
	//#region node_modules/@tanstack/vue-query/build/modern/queryClient.js
	var QueryClient = class extends QueryClient$1 {
		constructor(config = {}) {
			const vueQueryConfig = {
				defaultOptions: config.defaultOptions,
				queryCache: config.queryCache || new QueryCache(),
				mutationCache: config.mutationCache || new MutationCache()
			};
			super(vueQueryConfig);
			this.isRestoring = /* @__PURE__ */ ref(false);
		}
		isFetching(filters = {}) {
			return super.isFetching(cloneDeepUnref(filters));
		}
		isMutating(filters = {}) {
			return super.isMutating(cloneDeepUnref(filters));
		}
		getQueryData(queryKey) {
			return super.getQueryData(cloneDeepUnref(queryKey));
		}
		ensureQueryData(options) {
			return super.ensureQueryData(cloneDeepUnref(options));
		}
		getQueriesData(filters) {
			return super.getQueriesData(cloneDeepUnref(filters));
		}
		setQueryData(queryKey, updater, options = {}) {
			return super.setQueryData(cloneDeepUnref(queryKey), updater, cloneDeepUnref(options));
		}
		setQueriesData(filters, updater, options = {}) {
			return super.setQueriesData(cloneDeepUnref(filters), updater, cloneDeepUnref(options));
		}
		getQueryState(queryKey) {
			return super.getQueryState(cloneDeepUnref(queryKey));
		}
		removeQueries(filters = {}) {
			return super.removeQueries(cloneDeepUnref(filters));
		}
		resetQueries(filters = {}, options = {}) {
			return super.resetQueries(cloneDeepUnref(filters), cloneDeepUnref(options));
		}
		cancelQueries(filters = {}, options = {}) {
			return super.cancelQueries(cloneDeepUnref(filters), cloneDeepUnref(options));
		}
		invalidateQueries(filters = {}, options = {}) {
			const filtersCloned = cloneDeepUnref(filters);
			const optionsCloned = cloneDeepUnref(options);
			super.invalidateQueries({
				...filtersCloned,
				refetchType: "none"
			}, optionsCloned);
			if (filtersCloned.refetchType === "none") return Promise.resolve();
			const refetchFilters = {
				...filtersCloned,
				type: filtersCloned.refetchType ?? filtersCloned.type ?? "active"
			};
			return nextTick().then(() => {
				return super.refetchQueries(refetchFilters, optionsCloned);
			});
		}
		refetchQueries(filters = {}, options = {}) {
			return super.refetchQueries(cloneDeepUnref(filters), cloneDeepUnref(options));
		}
		fetchQuery(options) {
			return super.fetchQuery(cloneDeepUnref(options));
		}
		prefetchQuery(options) {
			return super.prefetchQuery(cloneDeepUnref(options));
		}
		fetchInfiniteQuery(options) {
			return super.fetchInfiniteQuery(cloneDeepUnref(options));
		}
		prefetchInfiniteQuery(options) {
			return super.prefetchInfiniteQuery(cloneDeepUnref(options));
		}
		setDefaultOptions(options) {
			super.setDefaultOptions(cloneDeepUnref(options));
		}
		setQueryDefaults(queryKey, options) {
			super.setQueryDefaults(cloneDeepUnref(queryKey), cloneDeepUnref(options));
		}
		getQueryDefaults(queryKey) {
			return super.getQueryDefaults(cloneDeepUnref(queryKey));
		}
		setMutationDefaults(mutationKey, options) {
			super.setMutationDefaults(cloneDeepUnref(mutationKey), cloneDeepUnref(options));
		}
		getMutationDefaults(mutationKey) {
			return super.getMutationDefaults(cloneDeepUnref(mutationKey));
		}
	};
	//#endregion
	//#region node_modules/@tanstack/vue-query/build/modern/vueQueryPlugin.js
	var VueQueryPlugin = { install: (app, options = {}) => {
		const clientKey = getClientKey(options.queryClientKey);
		let client;
		if ("queryClient" in options && options.queryClient) client = options.queryClient;
		else client = new QueryClient("queryClientConfig" in options ? options.queryClientConfig : void 0);
		if (!environmentManager.isServer()) client.mount();
		let persisterUnmount = () => {};
		if (options.clientPersister) {
			if (client.isRestoring) client.isRestoring.value = true;
			const [unmount, promise] = options.clientPersister(client);
			persisterUnmount = unmount;
			promise.then(() => {
				if (client.isRestoring) client.isRestoring.value = false;
				options.clientPersisterOnSuccess?.(client);
			});
		}
		const cleanup = () => {
			client.unmount();
			persisterUnmount();
		};
		if (app.onUnmount) app.onUnmount(cleanup);
		else {
			const originalUnmount = app.unmount;
			app.unmount = function vueQueryUnmount() {
				cleanup();
				originalUnmount();
			};
		}
		app.provide(clientKey, client);
	} };
	//#endregion
	//#region node_modules/@tanstack/vue-query/build/modern/useBaseQuery.js
	function useBaseQuery(Observer, options, queryClient) {
		const client = queryClient || useQueryClient();
		const defaultedOptions = computed(() => {
			let resolvedOptions = options;
			if (typeof resolvedOptions === "function") resolvedOptions = resolvedOptions();
			const clonedOptions = cloneDeepUnref(resolvedOptions);
			if (typeof clonedOptions.enabled === "function") clonedOptions.enabled = clonedOptions.enabled();
			const defaulted = client.defaultQueryOptions(clonedOptions);
			defaulted._optimisticResults = client.isRestoring?.value ? "isRestoring" : "optimistic";
			return defaulted;
		});
		const observer = new Observer(client, defaultedOptions.value);
		const state = defaultedOptions.value.shallow ? /* @__PURE__ */ shallowReactive(observer.getCurrentResult()) : /* @__PURE__ */ reactive(observer.getCurrentResult());
		let unsubscribe = () => {};
		if (client.isRestoring) watch(client.isRestoring, (isRestoring) => {
			if (!isRestoring) {
				unsubscribe();
				unsubscribe = observer.subscribe((result) => {
					updateState(state, result);
				});
			}
		}, { immediate: true });
		const updater = () => {
			observer.setOptions(defaultedOptions.value);
			updateState(state, observer.getCurrentResult());
		};
		watch(defaultedOptions, updater);
		onScopeDispose(() => {
			unsubscribe();
		});
		const refetch = (...args) => {
			updater();
			return state.refetch(...args);
		};
		const suspense = () => {
			return new Promise((resolve, reject) => {
				let stopWatch = () => {};
				const run = () => {
					if (defaultedOptions.value.enabled !== false) {
						observer.setOptions(defaultedOptions.value);
						const optimisticResult = observer.getOptimisticResult(defaultedOptions.value);
						if (optimisticResult.isStale) {
							stopWatch();
							observer.fetchOptimistic(defaultedOptions.value).then(resolve, (error) => {
								if (shouldThrowError(defaultedOptions.value.throwOnError, [error, observer.getCurrentQuery()])) reject(error);
								else resolve(observer.getCurrentResult());
							});
						} else {
							stopWatch();
							resolve(optimisticResult);
						}
					}
				};
				run();
				stopWatch = watch(defaultedOptions, run);
			});
		};
		watch(() => state.error, (error) => {
			if (state.isError && !state.isFetching && shouldThrowError(defaultedOptions.value.throwOnError, [error, observer.getCurrentQuery()])) throw error;
		});
		const object = /* @__PURE__ */ toRefs(defaultedOptions.value.shallow ? /* @__PURE__ */ shallowReadonly(state) : /* @__PURE__ */ readonly(state));
		for (const key in state) if (typeof state[key] === "function") object[key] = state[key];
		object.suspense = suspense;
		object.refetch = refetch;
		return object;
	}
	//#endregion
	//#region node_modules/@tanstack/vue-query/build/modern/useQuery.js
	function useQuery(options, queryClient) {
		return useBaseQuery(QueryObserver, options, queryClient);
	}
	//#endregion
	//#region node_modules/@tanstack/vue-query/build/modern/useMutation.js
	function useMutation(mutationOptions, queryClient) {
		const client = queryClient || useQueryClient();
		const options = computed(() => {
			const resolvedOptions = typeof mutationOptions === "function" ? mutationOptions() : mutationOptions;
			return client.defaultMutationOptions(cloneDeepUnref(resolvedOptions));
		});
		const observer = new MutationObserver$1(client, options.value);
		const state = options.value.shallow ? /* @__PURE__ */ shallowReactive(observer.getCurrentResult()) : /* @__PURE__ */ reactive(observer.getCurrentResult());
		const unsubscribe = observer.subscribe((result) => {
			updateState(state, result);
		});
		const mutate = (variables, mutateOptions) => {
			observer.mutate(variables, mutateOptions).catch(() => {});
		};
		watch(options, () => {
			observer.setOptions(options.value);
		});
		onScopeDispose(() => {
			unsubscribe();
		});
		const resultRefs = /* @__PURE__ */ toRefs(options.value.shallow ? /* @__PURE__ */ shallowReadonly(state) : /* @__PURE__ */ readonly(state));
		watch(() => state.error, (error) => {
			if (error && shouldThrowError(options.value.throwOnError, [error])) throw error;
		});
		return {
			...resultRefs,
			mutate,
			mutateAsync: state.mutate,
			reset: state.reset
		};
	}
	//#endregion
	//#region node_modules/pinia/dist/pinia.js
	/*!
	* pinia v4.0.2
	* (c) 2026 Eduardo San Martin Morote
	* @license MIT
	*/
	var IS_CLIENT = typeof window !== "undefined";
	/**
	* setActivePinia must be called to handle SSR at the top of functions like
	* `fetch`, `setup`, `serverPrefetch` and others
	*/
	var activePinia;
	/**
	* Sets or unsets the active pinia. Used in SSR and internally when calling
	* actions and getters
	*
	* @param pinia - Pinia instance
	*/
	var setActivePinia = (pinia) => activePinia = pinia;
	/**
	* Symbol used to provide/inject the pinia instance in the app. Used internally
	* and exposed for testing purposes and edge cases like storybook. Could break
	* in a minor, **USE AT YOUR OWN RISK**.
	*
	* For context, see:
	* - https://github.com/vuejs/pinia/issues/870
	* - https://github.com/vuejs/pinia/pull/2973
	*
	* @internal
	*/
	var piniaSymbol = Symbol();
	function isPlainObject(o) {
		return o && typeof o === "object" && Object.prototype.toString.call(o) === "[object Object]" && typeof o.toJSON !== "function";
	}
	var _global = /*#__PURE__*/ (() => typeof window === "object" && window.window === window ? window : typeof self === "object" && self.self === self ? self : typeof global === "object" && global.global === global ? global : typeof globalThis === "object" ? globalThis : { HTMLElement: null })();
	function bom(blob, { autoBom = false } = {}) {
		if (autoBom && /^\s*(?:text\/\S*|application\/xml|\S*\/\S*\+xml)\s*;.*charset\s*=\s*utf-8/i.test(blob.type)) return new Blob([String.fromCharCode(65279), blob], { type: blob.type });
		return blob;
	}
	function download(url, name, opts) {
		const xhr = new XMLHttpRequest();
		xhr.open("GET", url);
		xhr.responseType = "blob";
		xhr.onload = function() {
			saveAs(xhr.response, name, opts);
		};
		xhr.onerror = function() {
			console.error("could not download file");
		};
		xhr.send();
	}
	function corsEnabled(url) {
		const xhr = new XMLHttpRequest();
		xhr.open("HEAD", url, false);
		try {
			xhr.send();
		} catch (e) {}
		return xhr.status >= 200 && xhr.status <= 299;
	}
	function click(node) {
		try {
			node.dispatchEvent(new MouseEvent("click"));
		} catch (e) {
			const evt = new MouseEvent("click", {
				bubbles: true,
				cancelable: true,
				view: window,
				detail: 0,
				screenX: 80,
				screenY: 20,
				clientX: 80,
				clientY: 20,
				ctrlKey: false,
				altKey: false,
				shiftKey: false,
				metaKey: false,
				button: 0,
				relatedTarget: null
			});
			node.dispatchEvent(evt);
		}
	}
	var _navigator = typeof navigator === "object" ? navigator : { userAgent: "" };
	var isMacOSWebView = /*#__PURE__*/ (() => /Macintosh/.test(_navigator.userAgent) && /AppleWebKit/.test(_navigator.userAgent) && !/Safari/.test(_navigator.userAgent))();
	var saveAs = !IS_CLIENT ? () => {} : typeof HTMLAnchorElement !== "undefined" && "download" in HTMLAnchorElement.prototype && !isMacOSWebView ? downloadSaveAs : "msSaveOrOpenBlob" in _navigator ? msSaveAs : fileSaverSaveAs;
	function downloadSaveAs(blob, name = "download", opts) {
		const a = document.createElement("a");
		a.download = name;
		a.rel = "noopener";
		if (typeof blob === "string") {
			a.href = blob;
			if (a.origin !== location.origin) if (corsEnabled(a.href)) download(blob, name, opts);
			else {
				a.target = "_blank";
				click(a);
			}
			else click(a);
		} else {
			a.href = URL.createObjectURL(blob);
			setTimeout(function() {
				URL.revokeObjectURL(a.href);
			}, 4e4);
			setTimeout(function() {
				click(a);
			}, 0);
		}
	}
	function msSaveAs(blob, name = "download", opts) {
		if (typeof blob === "string") if (corsEnabled(blob)) download(blob, name, opts);
		else {
			const a = document.createElement("a");
			a.href = blob;
			a.target = "_blank";
			setTimeout(function() {
				click(a);
			});
		}
		else navigator.msSaveOrOpenBlob(bom(blob, opts), name);
	}
	function fileSaverSaveAs(blob, name, opts, popup) {
		popup = popup || open("", "_blank");
		if (popup) popup.document.title = popup.document.body.innerText = "downloading...";
		if (typeof blob === "string") return download(blob, name, opts);
		const force = blob.type === "application/octet-stream";
		const isSafari = /constructor/i.test(String(_global.HTMLElement)) || "safari" in _global;
		const isChromeIOS = /CriOS\/[\d]+/.test(navigator.userAgent);
		if ((isChromeIOS || force && isSafari || isMacOSWebView) && typeof FileReader !== "undefined") {
			const reader = new FileReader();
			reader.onloadend = function() {
				let url = reader.result;
				if (typeof url !== "string") {
					popup = null;
					throw new Error("Wrong reader.result type");
				}
				url = isChromeIOS ? url : url.replace(/^data:[^;]*;/, "data:attachment/file;");
				if (popup) popup.location.href = url;
				else location.assign(url);
				popup = null;
			};
			reader.readAsDataURL(blob);
		} else {
			const url = URL.createObjectURL(blob);
			if (popup) popup.location.assign(url);
			else location.href = url;
			popup = null;
			setTimeout(function() {
				URL.revokeObjectURL(url);
			}, 4e4);
		}
	}
	var { assign: assign$1 } = Object;
	/**
	* Creates a Pinia instance to be used by the application
	*/
	function createPinia() {
		const scope = effectScope(true);
		const state = scope.run(() => /* @__PURE__ */ ref({}));
		let _p = [];
		let toBeInstalled = [];
		const pinia = markRaw({
			install(app) {
				setActivePinia(pinia);
				pinia._a = app;
				app.provide(piniaSymbol, pinia);
				app.config.globalProperties.$pinia = pinia;
				toBeInstalled.forEach((plugin) => _p.push(plugin));
				toBeInstalled = [];
			},
			use(plugin) {
				if (!this._a) toBeInstalled.push(plugin);
				else _p.push(plugin);
				return this;
			},
			_p,
			_a: null,
			_e: scope,
			_s: /* @__PURE__ */ new Map(),
			state
		});
		return pinia;
	}
	var noop$1 = () => {};
	function addSubscription(subscriptions, callback, detached, onCleanup = noop$1) {
		subscriptions.add(callback);
		const removeSubscription = () => {
			subscriptions.delete(callback) && onCleanup();
		};
		if (!detached && getCurrentScope()) onScopeDispose(removeSubscription);
		return removeSubscription;
	}
	function triggerSubscriptions(subscriptions, ...args) {
		subscriptions.forEach((callback) => {
			callback(...args);
		});
	}
	var fallbackRunWithContext = (fn) => fn();
	/**
	* Marks a function as an action for `$onAction`
	* @internal
	*/
	var ACTION_MARKER = Symbol();
	/**
	* Action name symbol. Allows to add a name to an action after defining it
	* @internal
	*/
	var ACTION_NAME = Symbol();
	function mergeReactiveObjects(target, patchToApply) {
		if (target instanceof Map && patchToApply instanceof Map) patchToApply.forEach((value, key) => target.set(key, value));
		else if (target instanceof Set && patchToApply instanceof Set) patchToApply.forEach(target.add, target);
		for (const key in patchToApply) {
			if (!Object.hasOwn(patchToApply, key)) continue;
			const subPatch = patchToApply[key];
			const targetValue = target[key];
			if (isPlainObject(targetValue) && isPlainObject(subPatch) && Object.hasOwn(target, key) && !/* @__PURE__ */ isRef(subPatch) && !/* @__PURE__ */ isReactive(subPatch)) target[key] = mergeReactiveObjects(targetValue, subPatch);
			else target[key] = subPatch;
		}
		return target;
	}
	var skipHydrateSymbol = Symbol();
	/**
	* Returns whether a value should be hydrated
	*
	* @param obj - target variable
	* @returns true if `obj` should be hydrated
	*/
	function shouldHydrate(obj) {
		return !obj || typeof obj !== "object" || !Object.hasOwn(obj, skipHydrateSymbol);
	}
	var { assign: assign$2 } = Object;
	function isComputed(o) {
		return !!(/* @__PURE__ */ isRef(o) && o.effect);
	}
	function createOptionsStore(id, options, pinia, hot) {
		const { state, actions, getters } = options;
		const initialState = pinia.state.value[id];
		let store;
		function setup() {
			if (!initialState && true)
 /* istanbul ignore if */
			pinia.state.value[id] = state ? state() : {};
			return assign$2(/* @__PURE__ */ toRefs(pinia.state.value[id]), actions, Object.keys(getters || {}).reduce((computedGetters, name) => {
				computedGetters[name] = markRaw(computed(() => {
					setActivePinia(pinia);
					const store = pinia._s.get(id);
					return getters[name].call(store, store);
				}));
				return computedGetters;
			}, {}));
		}
		store = createSetupStore(id, setup, options, pinia, hot, true);
		return store;
	}
	function createSetupStore($id, setup, options = {}, pinia, hot, isOptionsStore) {
		let scope;
		const optionsForPlugin = assign$2({ actions: {} }, options);
		const $subscribeOptions = { deep: true };
		let isListening;
		let isSyncListening;
		let subscriptions = /* @__PURE__ */ new Set();
		let actionSubscriptions = /* @__PURE__ */ new Set();
		let debuggerEvents;
		const initialState = pinia.state.value[$id];
		if (!isOptionsStore && !initialState && true)
 /* istanbul ignore if */
		pinia.state.value[$id] = {};
		let activeListener;
		function $patch(partialStateOrMutator) {
			let subscriptionMutation;
			isListening = isSyncListening = false;
			if (typeof partialStateOrMutator === "function") {
				partialStateOrMutator(pinia.state.value[$id]);
				subscriptionMutation = {
					type: "patch function",
					storeId: $id,
					events: debuggerEvents
				};
			} else {
				mergeReactiveObjects(pinia.state.value[$id], partialStateOrMutator);
				subscriptionMutation = {
					type: "patch object",
					payload: partialStateOrMutator,
					storeId: $id,
					events: debuggerEvents
				};
			}
			const myListenerId = activeListener = Symbol();
			nextTick().then(() => {
				if (activeListener === myListenerId) isListening = true;
			});
			isSyncListening = true;
			triggerSubscriptions(subscriptions, subscriptionMutation, pinia.state.value[$id]);
		}
		const $reset = isOptionsStore ? function $reset() {
			const { state } = options;
			const newState = state ? state() : {};
			this.$patch(($state) => {
				assign$2($state, newState);
			});
		} : noop$1;
		function $dispose() {
			scope.stop();
			subscriptions.clear();
			actionSubscriptions.clear();
			pinia._s.delete($id);
		}
		/**
		* Helper that wraps function so it can be tracked with $onAction
		* @param fn - action to wrap
		* @param name - name of the action
		*/
		const action = (fn, name = "") => {
			if (ACTION_MARKER in fn) {
				fn[ACTION_NAME] = name;
				return fn;
			}
			const wrappedAction = function() {
				setActivePinia(pinia);
				const args = Array.from(arguments);
				const afterCallbackSet = /* @__PURE__ */ new Set();
				const onErrorCallbackSet = /* @__PURE__ */ new Set();
				function after(callback) {
					afterCallbackSet.add(callback);
				}
				function onError(callback) {
					onErrorCallbackSet.add(callback);
				}
				triggerSubscriptions(actionSubscriptions, {
					args,
					name: wrappedAction[ACTION_NAME],
					store,
					after,
					onError
				});
				let ret;
				try {
					ret = fn.apply(this && this.$id === $id ? this : store, args);
				} catch (error) {
					triggerSubscriptions(onErrorCallbackSet, error);
					throw error;
				}
				if (ret instanceof Promise) return ret.then((value) => {
					triggerSubscriptions(afterCallbackSet, value);
					return value;
				}).catch((error) => {
					triggerSubscriptions(onErrorCallbackSet, error);
					return Promise.reject(error);
				});
				triggerSubscriptions(afterCallbackSet, ret);
				return ret;
			};
			wrappedAction[ACTION_MARKER] = true;
			wrappedAction[ACTION_NAME] = name;
			return wrappedAction;
		};
		const store = /* @__PURE__ */ reactive({
			_p: pinia,
			$id,
			$onAction: addSubscription.bind(null, actionSubscriptions),
			$patch,
			$reset,
			$subscribe(callback, options = {}) {
				if (subscriptions.has(callback)) return noop$1;
				const removeSubscription = addSubscription(subscriptions, callback, options.detached, () => stopWatcher());
				const stopWatcher = scope.run(() => watch(() => pinia.state.value[$id], (state) => {
					if (options.flush === "sync" ? isSyncListening : isListening) callback({
						storeId: $id,
						type: "direct",
						events: debuggerEvents
					}, state);
				}, assign$2({}, $subscribeOptions, options)));
				return removeSubscription;
			},
			$dispose
		});
		pinia._s.set($id, store);
		const setupStore = (pinia._a && pinia._a.runWithContext || fallbackRunWithContext)(() => pinia._e.run(() => (scope = effectScope()).run(() => setup({ action }))));
		for (const key in setupStore) {
			const prop = setupStore[key];
			if (/* @__PURE__ */ isRef(prop) && !isComputed(prop) || /* @__PURE__ */ isReactive(prop)) {
				if (!isOptionsStore) {
					if (initialState && shouldHydrate(prop)) if (/* @__PURE__ */ isRef(prop)) prop.value = initialState[key];
					else mergeReactiveObjects(prop, initialState[key]);
					pinia.state.value[$id][key] = prop;
				}
			} else if (typeof prop === "function") {
				setupStore[key] = action(prop, key);
				optionsForPlugin.actions[key] = prop;
			}
		}
		/* istanbul ignore if */
		assign$2(store, setupStore);
		assign$2(/* @__PURE__ */ toRaw(store), setupStore);
		Object.defineProperty(store, "$state", {
			get: () => pinia.state.value[$id],
			set: (state) => {
				$patch(($state) => {
					assign$2($state, state);
				});
			}
		});
		pinia._p.forEach((extender) => {
			const extensions = scope.run(() => extender({
				store,
				app: pinia._a,
				pinia,
				options: optionsForPlugin
			}));
			assign$2(store, extensions);
		});
		if (initialState && isOptionsStore && options.hydrate) options.hydrate(store.$state, initialState);
		isListening = true;
		isSyncListening = true;
		return store;
	}
	/*! #__NO_SIDE_EFFECTS__ */
	function defineStore(id, setup, setupOptions) {
		let options;
		const isSetupStore = typeof setup === "function";
		options = isSetupStore ? setupOptions : setup;
		function useStore(pinia, hot) {
			const hasContext = hasInjectionContext();
			pinia = pinia || (hasContext ? inject(piniaSymbol, null) : null);
			if (pinia) setActivePinia(pinia);
			pinia = activePinia;
			if (!pinia._s.has(id)) {
				if (isSetupStore) createSetupStore(id, setup, options, pinia);
				else createOptionsStore(id, options, pinia);
			}
			return pinia._s.get(id);
		}
		useStore.$id = id;
		return useStore;
	}
	//#endregion
	//#region node_modules/@lucide/vue/dist/esm/shared/src/utils/isEmptyString.mjs
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var isEmptyString = (value) => value === "";
	//#endregion
	//#region node_modules/@lucide/vue/dist/esm/shared/src/utils/mergeClasses.mjs
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var mergeClasses = (...classes) => classes.filter((className, index, array) => {
		return Boolean(className) && className.trim() !== "" && array.indexOf(className) === index;
	}).join(" ").trim();
	//#endregion
	//#region node_modules/@lucide/vue/dist/esm/shared/src/utils/toKebabCase.mjs
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var toKebabCase = (string) => string.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();
	//#endregion
	//#region node_modules/@lucide/vue/dist/esm/shared/src/utils/toCamelCase.mjs
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var toCamelCase = (string) => string.replace(/^([A-Z])|[\s-_]+(\w)/g, (match, p1, p2) => p2 ? p2.toUpperCase() : p1.toLowerCase());
	//#endregion
	//#region node_modules/@lucide/vue/dist/esm/shared/src/utils/toPascalCase.mjs
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var toPascalCase = (string) => {
		const camelCase = toCamelCase(string);
		return camelCase.charAt(0).toUpperCase() + camelCase.slice(1);
	};
	//#endregion
	//#region node_modules/@lucide/vue/dist/esm/defaultAttributes.mjs
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var defaultAttributes = {
		xmlns: "http://www.w3.org/2000/svg",
		width: 24,
		height: 24,
		viewBox: "0 0 24 24",
		fill: "none",
		stroke: "currentColor",
		"stroke-width": 2,
		"stroke-linecap": "round",
		"stroke-linejoin": "round"
	};
	//#endregion
	//#region node_modules/@lucide/vue/dist/esm/context.mjs
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var LUCIDE_CONTEXT = /* @__PURE__ */ Symbol("lucide-icons");
	function useLucideProps() {
		return inject(LUCIDE_CONTEXT, {});
	}
	//#endregion
	//#region node_modules/@lucide/vue/dist/esm/Icon.mjs
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var Icon = ({ name, iconNode, "icon-node": iconNodeKebabCase, absoluteStrokeWidth, "absolute-stroke-width": absoluteStrokeWidthKebabCase, strokeWidth, "stroke-width": strokeWidthKebabCase, size, color, ...props }, { slots }) => {
		const { size: contextSize, color: contextColor, strokeWidth: contextStrokeWidth = 2, absoluteStrokeWidth: contextAbsoluteStrokeWidth = false, class: contextClass = "" } = useLucideProps();
		const calculatedStrokeWidth = computed(() => {
			const isAbsoluteStrokeWidth = isEmptyString(absoluteStrokeWidth) || isEmptyString(absoluteStrokeWidthKebabCase) || absoluteStrokeWidth === true || absoluteStrokeWidthKebabCase === true || contextAbsoluteStrokeWidth === true;
			const strokeWidthValue = strokeWidth || strokeWidthKebabCase || contextStrokeWidth || defaultAttributes["stroke-width"];
			if (isAbsoluteStrokeWidth) return Number(strokeWidthValue) * 24 / Number(size ?? contextSize ?? defaultAttributes.width);
			return strokeWidthValue;
		});
		return h("svg", {
			...defaultAttributes,
			...props,
			width: size ?? contextSize ?? defaultAttributes.width,
			height: size ?? contextSize ?? defaultAttributes.height,
			stroke: color ?? contextColor ?? defaultAttributes.stroke,
			"stroke-width": calculatedStrokeWidth.value,
			class: mergeClasses("lucide", contextClass, ...name ? [`lucide-${toKebabCase(toPascalCase(name))}-icon`, `lucide-${toKebabCase(name)}`] : ["lucide-icon"])
		}, [...(iconNode ?? iconNodeKebabCase ?? []).map((child) => h(...child)), ...slots.default ? [slots.default()] : []]);
	};
	//#endregion
	//#region node_modules/@lucide/vue/dist/esm/createLucideIcon.mjs
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var createLucideIcon = (iconName, iconNode) => (props, { slots, attrs }) => h(Icon, {
		...attrs,
		...props,
		iconNode,
		name: iconName
	}, slots.default ? { default: slots.default } : void 0);
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var Archive = createLucideIcon("archive", [
		["rect", {
			width: "20",
			height: "5",
			x: "2",
			y: "3",
			rx: "1",
			key: "1wp1u1"
		}],
		["path", {
			d: "M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8",
			key: "1s80jp"
		}],
		["path", {
			d: "M10 12h4",
			key: "a56b0p"
		}]
	]);
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var FolderOpen = createLucideIcon("folder-open", [["path", {
		d: "m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2",
		key: "usdka0"
	}]]);
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var LogOut = createLucideIcon("log-out", [
		["path", {
			d: "m16 17 5-5-5-5",
			key: "1bji2h"
		}],
		["path", {
			d: "M21 12H9",
			key: "dn1m92"
		}],
		["path", {
			d: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4",
			key: "1uf3rs"
		}]
	]);
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var PanelLeftClose = createLucideIcon("panel-left-close", [
		["rect", {
			width: "18",
			height: "18",
			x: "3",
			y: "3",
			rx: "2",
			key: "afitv7"
		}],
		["path", {
			d: "M9 3v18",
			key: "fh3hqa"
		}],
		["path", {
			d: "m16 15-3-3 3-3",
			key: "14y99z"
		}]
	]);
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var Plus = createLucideIcon("plus", [["path", {
		d: "M5 12h14",
		key: "1ays0h"
	}], ["path", {
		d: "M12 5v14",
		key: "s699le"
	}]]);
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var RefreshCw = createLucideIcon("refresh-cw", [
		["path", {
			d: "M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8",
			key: "v9h5vc"
		}],
		["path", {
			d: "M21 3v5h-5",
			key: "1q7to0"
		}],
		["path", {
			d: "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16",
			key: "3uifl3"
		}],
		["path", {
			d: "M8 16H3v5",
			key: "1cv678"
		}]
	]);
	/**
	* @license @lucide/vue v1.30.0 - ISC
	*
	* This source code is licensed under the ISC license.
	* See the LICENSE file in the root directory of this source tree.
	*/
	var Trash2 = createLucideIcon("trash-2", [
		["path", {
			d: "M10 11v6",
			key: "nco0om"
		}],
		["path", {
			d: "M14 11v6",
			key: "outv1u"
		}],
		["path", {
			d: "M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6",
			key: "miytrc"
		}],
		["path", {
			d: "M3 6h18",
			key: "d0wm0j"
		}],
		["path", {
			d: "M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2",
			key: "e791ji"
		}]
	]);
	//#endregion
	//#region node_modules/vue-router/dist/devtools-EWN81iOl.mjs
	/*!
	* vue-router v4.6.4
	* (c) 2025 Eduardo San Martin Morote
	* @license MIT
	*/
	var isBrowser = typeof document !== "undefined";
	/**
	* Allows differentiating lazy components from functional components and vue-class-component
	* @internal
	*
	* @param component
	*/
	function isRouteComponent(component) {
		return typeof component === "object" || "displayName" in component || "props" in component || "__vccOpts" in component;
	}
	function isESModule(obj) {
		return obj.__esModule || obj[Symbol.toStringTag] === "Module" || obj.default && isRouteComponent(obj.default);
	}
	var assign = Object.assign;
	function applyToParams(fn, params) {
		const newParams = {};
		for (const key in params) {
			const value = params[key];
			newParams[key] = isArray(value) ? value.map(fn) : fn(value);
		}
		return newParams;
	}
	var noop = () => {};
	/**
	* Typesafe alternative to Array.isArray
	* https://github.com/microsoft/TypeScript/pull/48228
	*
	* @internal
	*/
	var isArray = Array.isArray;
	function mergeOptions(defaults, partialOptions) {
		const options = {};
		for (const key in defaults) options[key] = key in partialOptions ? partialOptions[key] : defaults[key];
		return options;
	}
	/**
	* Encoding Rules (␣ = Space)
	* - Path: ␣ " < > # ? { }
	* - Query: ␣ " < > # & =
	* - Hash: ␣ " < > `
	*
	* On top of that, the RFC3986 (https://tools.ietf.org/html/rfc3986#section-2.2)
	* defines some extra characters to be encoded. Most browsers do not encode them
	* in encodeURI https://github.com/whatwg/url/issues/369, so it may be safer to
	* also encode `!'()*`. Leaving un-encoded only ASCII alphanumeric(`a-zA-Z0-9`)
	* plus `-._~`. This extra safety should be applied to query by patching the
	* string returned by encodeURIComponent encodeURI also encodes `[\]^`. `\`
	* should be encoded to avoid ambiguity. Browsers (IE, FF, C) transform a `\`
	* into a `/` if directly typed in. The _backtick_ (`````) should also be
	* encoded everywhere because some browsers like FF encode it when directly
	* written while others don't. Safari and IE don't encode ``"<>{}``` in hash.
	*/
	var HASH_RE = /#/g;
	var AMPERSAND_RE = /&/g;
	var SLASH_RE = /\//g;
	var EQUAL_RE = /=/g;
	var IM_RE = /\?/g;
	var PLUS_RE = /\+/g;
	/**
	* NOTE: It's not clear to me if we should encode the + symbol in queries, it
	* seems to be less flexible than not doing so and I can't find out the legacy
	* systems requiring this for regular requests like text/html. In the standard,
	* the encoding of the plus character is only mentioned for
	* application/x-www-form-urlencoded
	* (https://url.spec.whatwg.org/#urlencoded-parsing) and most browsers seems lo
	* leave the plus character as is in queries. To be more flexible, we allow the
	* plus character on the query, but it can also be manually encoded by the user.
	*
	* Resources:
	* - https://url.spec.whatwg.org/#urlencoded-parsing
	* - https://stackoverflow.com/questions/1634271/url-encoding-the-space-character-or-20
	*/
	var ENC_BRACKET_OPEN_RE = /%5B/g;
	var ENC_BRACKET_CLOSE_RE = /%5D/g;
	var ENC_CARET_RE = /%5E/g;
	var ENC_BACKTICK_RE = /%60/g;
	var ENC_CURLY_OPEN_RE = /%7B/g;
	var ENC_PIPE_RE = /%7C/g;
	var ENC_CURLY_CLOSE_RE = /%7D/g;
	var ENC_SPACE_RE = /%20/g;
	/**
	* Encode characters that need to be encoded on the path, search and hash
	* sections of the URL.
	*
	* @internal
	* @param text - string to encode
	* @returns encoded string
	*/
	function commonEncode(text) {
		return text == null ? "" : encodeURI("" + text).replace(ENC_PIPE_RE, "|").replace(ENC_BRACKET_OPEN_RE, "[").replace(ENC_BRACKET_CLOSE_RE, "]");
	}
	/**
	* Encode characters that need to be encoded on the hash section of the URL.
	*
	* @param text - string to encode
	* @returns encoded string
	*/
	function encodeHash(text) {
		return commonEncode(text).replace(ENC_CURLY_OPEN_RE, "{").replace(ENC_CURLY_CLOSE_RE, "}").replace(ENC_CARET_RE, "^");
	}
	/**
	* Encode characters that need to be encoded query values on the query
	* section of the URL.
	*
	* @param text - string to encode
	* @returns encoded string
	*/
	function encodeQueryValue(text) {
		return commonEncode(text).replace(PLUS_RE, "%2B").replace(ENC_SPACE_RE, "+").replace(HASH_RE, "%23").replace(AMPERSAND_RE, "%26").replace(ENC_BACKTICK_RE, "`").replace(ENC_CURLY_OPEN_RE, "{").replace(ENC_CURLY_CLOSE_RE, "}").replace(ENC_CARET_RE, "^");
	}
	/**
	* Like `encodeQueryValue` but also encodes the `=` character.
	*
	* @param text - string to encode
	*/
	function encodeQueryKey(text) {
		return encodeQueryValue(text).replace(EQUAL_RE, "%3D");
	}
	/**
	* Encode characters that need to be encoded on the path section of the URL.
	*
	* @param text - string to encode
	* @returns encoded string
	*/
	function encodePath(text) {
		return commonEncode(text).replace(HASH_RE, "%23").replace(IM_RE, "%3F");
	}
	/**
	* Encode characters that need to be encoded on the path section of the URL as a
	* param. This function encodes everything {@link encodePath} does plus the
	* slash (`/`) character. If `text` is `null` or `undefined`, returns an empty
	* string instead.
	*
	* @param text - string to encode
	* @returns encoded string
	*/
	function encodeParam(text) {
		return encodePath(text).replace(SLASH_RE, "%2F");
	}
	function decode(text) {
		if (text == null) return null;
		try {
			return decodeURIComponent("" + text);
		} catch (err) {}
		return "" + text;
	}
	var TRAILING_SLASH_RE = /\/$/;
	var removeTrailingSlash = (path) => path.replace(TRAILING_SLASH_RE, "");
	/**
	* Transforms a URI into a normalized history location
	*
	* @param parseQuery
	* @param location - URI to normalize
	* @param currentLocation - current absolute location. Allows resolving relative
	* paths. Must start with `/`. Defaults to `/`
	* @returns a normalized history location
	*/
	function parseURL(parseQuery$1, location, currentLocation = "/") {
		let path, query = {}, searchString = "", hash = "";
		const hashPos = location.indexOf("#");
		let searchPos = location.indexOf("?");
		searchPos = hashPos >= 0 && searchPos > hashPos ? -1 : searchPos;
		if (searchPos >= 0) {
			path = location.slice(0, searchPos);
			searchString = location.slice(searchPos, hashPos > 0 ? hashPos : location.length);
			query = parseQuery$1(searchString.slice(1));
		}
		if (hashPos >= 0) {
			path = path || location.slice(0, hashPos);
			hash = location.slice(hashPos, location.length);
		}
		path = resolveRelativePath(path != null ? path : location, currentLocation);
		return {
			fullPath: path + searchString + hash,
			path,
			query,
			hash: decode(hash)
		};
	}
	/**
	* Stringifies a URL object
	*
	* @param stringifyQuery
	* @param location
	*/
	function stringifyURL(stringifyQuery$1, location) {
		const query = location.query ? stringifyQuery$1(location.query) : "";
		return location.path + (query && "?") + query + (location.hash || "");
	}
	/**
	* Strips off the base from the beginning of a location.pathname in a non-case-sensitive way.
	*
	* @param pathname - location.pathname
	* @param base - base to strip off
	*/
	function stripBase(pathname, base) {
		if (!base || !pathname.toLowerCase().startsWith(base.toLowerCase())) return pathname;
		return pathname.slice(base.length) || "/";
	}
	/**
	* Checks if two RouteLocation are equal. This means that both locations are
	* pointing towards the same {@link RouteRecord} and that all `params`, `query`
	* parameters and `hash` are the same
	*
	* @param stringifyQuery - A function that takes a query object of type LocationQueryRaw and returns a string representation of it.
	* @param a - first {@link RouteLocation}
	* @param b - second {@link RouteLocation}
	*/
	function isSameRouteLocation(stringifyQuery$1, a, b) {
		const aLastIndex = a.matched.length - 1;
		const bLastIndex = b.matched.length - 1;
		return aLastIndex > -1 && aLastIndex === bLastIndex && isSameRouteRecord(a.matched[aLastIndex], b.matched[bLastIndex]) && isSameRouteLocationParams(a.params, b.params) && stringifyQuery$1(a.query) === stringifyQuery$1(b.query) && a.hash === b.hash;
	}
	/**
	* Check if two `RouteRecords` are equal. Takes into account aliases: they are
	* considered equal to the `RouteRecord` they are aliasing.
	*
	* @param a - first {@link RouteRecord}
	* @param b - second {@link RouteRecord}
	*/
	function isSameRouteRecord(a, b) {
		return (a.aliasOf || a) === (b.aliasOf || b);
	}
	function isSameRouteLocationParams(a, b) {
		if (Object.keys(a).length !== Object.keys(b).length) return false;
		for (var key in a) if (!isSameRouteLocationParamsValue(a[key], b[key])) return false;
		return true;
	}
	function isSameRouteLocationParamsValue(a, b) {
		return isArray(a) ? isEquivalentArray(a, b) : isArray(b) ? isEquivalentArray(b, a) : a?.valueOf() === b?.valueOf();
	}
	/**
	* Check if two arrays are the same or if an array with one single entry is the
	* same as another primitive value. Used to check query and parameters
	*
	* @param a - array of values
	* @param b - array of values or a single value
	*/
	function isEquivalentArray(a, b) {
		return isArray(b) ? a.length === b.length && a.every((value, i) => value === b[i]) : a.length === 1 && a[0] === b;
	}
	/**
	* Resolves a relative path that starts with `.`.
	*
	* @param to - path location we are resolving
	* @param from - currentLocation.path, should start with `/`
	*/
	function resolveRelativePath(to, from) {
		if (to.startsWith("/")) return to;
		if (!to) return from;
		const fromSegments = from.split("/");
		const toSegments = to.split("/");
		const lastToSegment = toSegments[toSegments.length - 1];
		if (lastToSegment === ".." || lastToSegment === ".") toSegments.push("");
		let position = fromSegments.length - 1;
		let toPosition;
		let segment;
		for (toPosition = 0; toPosition < toSegments.length; toPosition++) {
			segment = toSegments[toPosition];
			if (segment === ".") continue;
			if (segment === "..") {
				if (position > 1) position--;
			} else break;
		}
		return fromSegments.slice(0, position).join("/") + "/" + toSegments.slice(toPosition).join("/");
	}
	/**
	* Initial route location where the router is. Can be used in navigation guards
	* to differentiate the initial navigation.
	*
	* @example
	* ```js
	* import { START_LOCATION } from 'vue-router'
	*
	* router.beforeEach((to, from) => {
	*   if (from === START_LOCATION) {
	*     // initial navigation
	*   }
	* })
	* ```
	*/
	var START_LOCATION_NORMALIZED = {
		path: "/",
		name: void 0,
		params: {},
		query: {},
		hash: "",
		fullPath: "/",
		matched: [],
		meta: {},
		redirectedFrom: void 0
	};
	var NavigationType = /* @__PURE__ */ function(NavigationType$1) {
		NavigationType$1["pop"] = "pop";
		NavigationType$1["push"] = "push";
		return NavigationType$1;
	}({});
	var NavigationDirection = /* @__PURE__ */ function(NavigationDirection$1) {
		NavigationDirection$1["back"] = "back";
		NavigationDirection$1["forward"] = "forward";
		NavigationDirection$1["unknown"] = "";
		return NavigationDirection$1;
	}({});
	/**
	* Normalizes a base by removing any trailing slash and reading the base tag if
	* present.
	*
	* @param base - base to normalize
	*/
	function normalizeBase(base) {
		if (!base) if (isBrowser) {
			const baseEl = document.querySelector("base");
			base = baseEl && baseEl.getAttribute("href") || "/";
			base = base.replace(/^\w+:\/\/[^\/]+/, "");
		} else base = "/";
		if (base[0] !== "/" && base[0] !== "#") base = "/" + base;
		return removeTrailingSlash(base);
	}
	var BEFORE_HASH_RE = /^[^#]+#/;
	function createHref(base, location) {
		return base.replace(BEFORE_HASH_RE, "#") + location;
	}
	function getElementPosition(el, offset) {
		const docRect = document.documentElement.getBoundingClientRect();
		const elRect = el.getBoundingClientRect();
		return {
			behavior: offset.behavior,
			left: elRect.left - docRect.left - (offset.left || 0),
			top: elRect.top - docRect.top - (offset.top || 0)
		};
	}
	var computeScrollPosition = () => ({
		left: window.scrollX,
		top: window.scrollY
	});
	function scrollToPosition(position) {
		let scrollToOptions;
		if ("el" in position) {
			const positionEl = position.el;
			const isIdSelector = typeof positionEl === "string" && positionEl.startsWith("#");
			const el = typeof positionEl === "string" ? isIdSelector ? document.getElementById(positionEl.slice(1)) : document.querySelector(positionEl) : positionEl;
			if (!el) return;
			scrollToOptions = getElementPosition(el, position);
		} else scrollToOptions = position;
		if ("scrollBehavior" in document.documentElement.style) window.scrollTo(scrollToOptions);
		else window.scrollTo(scrollToOptions.left != null ? scrollToOptions.left : window.scrollX, scrollToOptions.top != null ? scrollToOptions.top : window.scrollY);
	}
	function getScrollKey(path, delta) {
		return (history.state ? history.state.position - delta : -1) + path;
	}
	var scrollPositions = /* @__PURE__ */ new Map();
	function saveScrollPosition(key, scrollPosition) {
		scrollPositions.set(key, scrollPosition);
	}
	function getSavedScrollPosition(key) {
		const scroll = scrollPositions.get(key);
		scrollPositions.delete(key);
		return scroll;
	}
	/**
	* ScrollBehavior instance used by the router to compute and restore the scroll
	* position when navigating.
	*/
	function isRouteLocation(route) {
		return typeof route === "string" || route && typeof route === "object";
	}
	function isRouteName(name) {
		return typeof name === "string" || typeof name === "symbol";
	}
	/**
	* Flags so we can combine them when checking for multiple errors. This is the internal version of
	* {@link NavigationFailureType}.
	*
	* @internal
	*/
	var ErrorTypes = /* @__PURE__ */ function(ErrorTypes$1) {
		ErrorTypes$1[ErrorTypes$1["MATCHER_NOT_FOUND"] = 1] = "MATCHER_NOT_FOUND";
		ErrorTypes$1[ErrorTypes$1["NAVIGATION_GUARD_REDIRECT"] = 2] = "NAVIGATION_GUARD_REDIRECT";
		ErrorTypes$1[ErrorTypes$1["NAVIGATION_ABORTED"] = 4] = "NAVIGATION_ABORTED";
		ErrorTypes$1[ErrorTypes$1["NAVIGATION_CANCELLED"] = 8] = "NAVIGATION_CANCELLED";
		ErrorTypes$1[ErrorTypes$1["NAVIGATION_DUPLICATED"] = 16] = "NAVIGATION_DUPLICATED";
		return ErrorTypes$1;
	}({});
	var NavigationFailureSymbol = Symbol("");
	ErrorTypes.MATCHER_NOT_FOUND, ErrorTypes.NAVIGATION_GUARD_REDIRECT, ErrorTypes.NAVIGATION_ABORTED, ErrorTypes.NAVIGATION_CANCELLED, ErrorTypes.NAVIGATION_DUPLICATED;
	/**
	* Creates a typed NavigationFailure object.
	* @internal
	* @param type - NavigationFailureType
	* @param params - { from, to }
	*/
	function createRouterError(type, params) {
		return assign(/* @__PURE__ */ new Error(), {
			type,
			[NavigationFailureSymbol]: true
		}, params);
	}
	function isNavigationFailure(error, type) {
		return error instanceof Error && NavigationFailureSymbol in error && (type == null || !!(error.type & type));
	}
	/**
	* Transforms a queryString into a {@link LocationQuery} object. Accept both, a
	* version with the leading `?` and without Should work as URLSearchParams
	
	* @internal
	*
	* @param search - search string to parse
	* @returns a query object
	*/
	function parseQuery(search) {
		const query = {};
		if (search === "" || search === "?") return query;
		const searchParams = (search[0] === "?" ? search.slice(1) : search).split("&");
		for (let i = 0; i < searchParams.length; ++i) {
			const searchParam = searchParams[i].replace(PLUS_RE, " ");
			const eqPos = searchParam.indexOf("=");
			const key = decode(eqPos < 0 ? searchParam : searchParam.slice(0, eqPos));
			const value = eqPos < 0 ? null : decode(searchParam.slice(eqPos + 1));
			if (key in query) {
				let currentValue = query[key];
				if (!isArray(currentValue)) currentValue = query[key] = [currentValue];
				currentValue.push(value);
			} else query[key] = value;
		}
		return query;
	}
	/**
	* Stringifies a {@link LocationQueryRaw} object. Like `URLSearchParams`, it
	* doesn't prepend a `?`
	*
	* @internal
	*
	* @param query - query object to stringify
	* @returns string version of the query without the leading `?`
	*/
	function stringifyQuery(query) {
		let search = "";
		for (let key in query) {
			const value = query[key];
			key = encodeQueryKey(key);
			if (value == null) {
				if (value !== void 0) search += (search.length ? "&" : "") + key;
				continue;
			}
			(isArray(value) ? value.map((v) => v && encodeQueryValue(v)) : [value && encodeQueryValue(value)]).forEach((value$1) => {
				if (value$1 !== void 0) {
					search += (search.length ? "&" : "") + key;
					if (value$1 != null) search += "=" + value$1;
				}
			});
		}
		return search;
	}
	/**
	* Transforms a {@link LocationQueryRaw} into a {@link LocationQuery} by casting
	* numbers into strings, removing keys with an undefined value and replacing
	* undefined with null in arrays
	*
	* @param query - query object to normalize
	* @returns a normalized query object
	*/
	function normalizeQuery(query) {
		const normalizedQuery = {};
		for (const key in query) {
			const value = query[key];
			if (value !== void 0) normalizedQuery[key] = isArray(value) ? value.map((v) => v == null ? null : "" + v) : value == null ? value : "" + value;
		}
		return normalizedQuery;
	}
	/**
	* RouteRecord being rendered by the closest ancestor Router View. Used for
	* `onBeforeRouteUpdate` and `onBeforeRouteLeave`. rvlm stands for Router View
	* Location Matched
	*
	* @internal
	*/
	var matchedRouteKey = Symbol("");
	/**
	* Allows overriding the router view depth to control which component in
	* `matched` is rendered. rvd stands for Router View Depth
	*
	* @internal
	*/
	var viewDepthKey = Symbol("");
	/**
	* Allows overriding the router instance returned by `useRouter` in tests. r
	* stands for router
	*
	* @internal
	*/
	var routerKey = Symbol("");
	/**
	* Allows overriding the current route returned by `useRoute` in tests. rl
	* stands for route location
	*
	* @internal
	*/
	var routeLocationKey = Symbol("");
	/**
	* Allows overriding the current route used by router-view. Internally this is
	* used when the `route` prop is passed.
	*
	* @internal
	*/
	var routerViewLocationKey = Symbol("");
	/**
	* Create a list of callbacks that can be reset. Used to create before and after navigation guards list
	*/
	function useCallbacks() {
		let handlers = [];
		function add(handler) {
			handlers.push(handler);
			return () => {
				const i = handlers.indexOf(handler);
				if (i > -1) handlers.splice(i, 1);
			};
		}
		function reset() {
			handlers = [];
		}
		return {
			add,
			list: () => handlers.slice(),
			reset
		};
	}
	function guardToPromiseFn(guard, to, from, record, name, runWithContext = (fn) => fn()) {
		const enterCallbackArray = record && (record.enterCallbacks[name] = record.enterCallbacks[name] || []);
		return () => new Promise((resolve, reject) => {
			const next = (valid) => {
				if (valid === false) reject(createRouterError(ErrorTypes.NAVIGATION_ABORTED, {
					from,
					to
				}));
				else if (valid instanceof Error) reject(valid);
				else if (isRouteLocation(valid)) reject(createRouterError(ErrorTypes.NAVIGATION_GUARD_REDIRECT, {
					from: to,
					to: valid
				}));
				else {
					if (enterCallbackArray && record.enterCallbacks[name] === enterCallbackArray && typeof valid === "function") enterCallbackArray.push(valid);
					resolve();
				}
			};
			const guardReturn = runWithContext(() => guard.call(record && record.instances[name], to, from, next));
			let guardCall = Promise.resolve(guardReturn);
			if (guard.length < 3) guardCall = guardCall.then(next);
			guardCall.catch((err) => reject(err));
		});
	}
	function extractComponentsGuards(matched, guardType, to, from, runWithContext = (fn) => fn()) {
		const guards = [];
		for (const record of matched) for (const name in record.components) {
			let rawComponent = record.components[name];
			if (guardType !== "beforeRouteEnter" && !record.instances[name]) continue;
			if (isRouteComponent(rawComponent)) {
				const guard = (rawComponent.__vccOpts || rawComponent)[guardType];
				guard && guards.push(guardToPromiseFn(guard, to, from, record, name, runWithContext));
			} else {
				let componentPromise = rawComponent();
				guards.push(() => componentPromise.then((resolved) => {
					if (!resolved) throw new Error(`Couldn't resolve component "${name}" at "${record.path}"`);
					const resolvedComponent = isESModule(resolved) ? resolved.default : resolved;
					record.mods[name] = resolved;
					record.components[name] = resolvedComponent;
					const guard = (resolvedComponent.__vccOpts || resolvedComponent)[guardType];
					return guard && guardToPromiseFn(guard, to, from, record, name, runWithContext)();
				}));
			}
		}
		return guards;
	}
	/**
	* Split the leaving, updating, and entering records.
	* @internal
	*
	* @param  to - Location we are navigating to
	* @param from - Location we are navigating from
	*/
	function extractChangingRecords(to, from) {
		const leavingRecords = [];
		const updatingRecords = [];
		const enteringRecords = [];
		const len = Math.max(from.matched.length, to.matched.length);
		for (let i = 0; i < len; i++) {
			const recordFrom = from.matched[i];
			if (recordFrom) if (to.matched.find((record) => isSameRouteRecord(record, recordFrom))) updatingRecords.push(recordFrom);
			else leavingRecords.push(recordFrom);
			const recordTo = to.matched[i];
			if (recordTo) {
				if (!from.matched.find((record) => isSameRouteRecord(record, recordTo))) enteringRecords.push(recordTo);
			}
		}
		return [
			leavingRecords,
			updatingRecords,
			enteringRecords
		];
	}
	//#endregion
	//#region node_modules/vue-router/dist/vue-router.mjs
	/*!
	* vue-router v4.6.4
	* (c) 2025 Eduardo San Martin Morote
	* @license MIT
	*/
	var createBaseLocation = () => location.protocol + "//" + location.host;
	/**
	* Creates a normalized history location from a window.location object
	* @param base - The base path
	* @param location - The window.location object
	*/
	function createCurrentLocation(base, location$1) {
		const { pathname, search, hash } = location$1;
		const hashPos = base.indexOf("#");
		if (hashPos > -1) {
			let slicePos = hash.includes(base.slice(hashPos)) ? base.slice(hashPos).length : 1;
			let pathFromHash = hash.slice(slicePos);
			if (pathFromHash[0] !== "/") pathFromHash = "/" + pathFromHash;
			return stripBase(pathFromHash, "");
		}
		return stripBase(pathname, base) + search + hash;
	}
	function useHistoryListeners(base, historyState, currentLocation, replace) {
		let listeners = [];
		let teardowns = [];
		let pauseState = null;
		const popStateHandler = ({ state }) => {
			const to = createCurrentLocation(base, location);
			const from = currentLocation.value;
			const fromState = historyState.value;
			let delta = 0;
			if (state) {
				currentLocation.value = to;
				historyState.value = state;
				if (pauseState && pauseState === from) {
					pauseState = null;
					return;
				}
				delta = fromState ? state.position - fromState.position : 0;
			} else replace(to);
			listeners.forEach((listener) => {
				listener(currentLocation.value, from, {
					delta,
					type: NavigationType.pop,
					direction: delta ? delta > 0 ? NavigationDirection.forward : NavigationDirection.back : NavigationDirection.unknown
				});
			});
		};
		function pauseListeners() {
			pauseState = currentLocation.value;
		}
		function listen(callback) {
			listeners.push(callback);
			const teardown = () => {
				const index = listeners.indexOf(callback);
				if (index > -1) listeners.splice(index, 1);
			};
			teardowns.push(teardown);
			return teardown;
		}
		function beforeUnloadListener() {
			if (document.visibilityState === "hidden") {
				const { history: history$1 } = window;
				if (!history$1.state) return;
				history$1.replaceState(assign({}, history$1.state, { scroll: computeScrollPosition() }), "");
			}
		}
		function destroy() {
			for (const teardown of teardowns) teardown();
			teardowns = [];
			window.removeEventListener("popstate", popStateHandler);
			window.removeEventListener("pagehide", beforeUnloadListener);
			document.removeEventListener("visibilitychange", beforeUnloadListener);
		}
		window.addEventListener("popstate", popStateHandler);
		window.addEventListener("pagehide", beforeUnloadListener);
		document.addEventListener("visibilitychange", beforeUnloadListener);
		return {
			pauseListeners,
			listen,
			destroy
		};
	}
	/**
	* Creates a state object
	*/
	function buildState(back, current, forward, replaced = false, computeScroll = false) {
		return {
			back,
			current,
			forward,
			replaced,
			position: window.history.length,
			scroll: computeScroll ? computeScrollPosition() : null
		};
	}
	function useHistoryStateNavigation(base) {
		const { history: history$1, location: location$1 } = window;
		const currentLocation = { value: createCurrentLocation(base, location$1) };
		const historyState = { value: history$1.state };
		if (!historyState.value) changeLocation(currentLocation.value, {
			back: null,
			current: currentLocation.value,
			forward: null,
			position: history$1.length - 1,
			replaced: true,
			scroll: null
		}, true);
		function changeLocation(to, state, replace$1) {
			/**
			* if a base tag is provided, and we are on a normal domain, we have to
			* respect the provided `base` attribute because pushState() will use it and
			* potentially erase anything before the `#` like at
			* https://github.com/vuejs/router/issues/685 where a base of
			* `/folder/#` but a base of `/` would erase the `/folder/` section. If
			* there is no host, the `<base>` tag makes no sense and if there isn't a
			* base tag we can just use everything after the `#`.
			*/
			const hashIndex = base.indexOf("#");
			const url = hashIndex > -1 ? (location$1.host && document.querySelector("base") ? base : base.slice(hashIndex)) + to : createBaseLocation() + base + to;
			try {
				history$1[replace$1 ? "replaceState" : "pushState"](state, "", url);
				historyState.value = state;
			} catch (err) {
				console.error(err);
				location$1[replace$1 ? "replace" : "assign"](url);
			}
		}
		function replace(to, data) {
			changeLocation(to, assign({}, history$1.state, buildState(historyState.value.back, to, historyState.value.forward, true), data, { position: historyState.value.position }), true);
			currentLocation.value = to;
		}
		function push(to, data) {
			const currentState = assign({}, historyState.value, history$1.state, {
				forward: to,
				scroll: computeScrollPosition()
			});
			changeLocation(currentState.current, currentState, true);
			changeLocation(to, assign({}, buildState(currentLocation.value, to, null), { position: currentState.position + 1 }, data), false);
			currentLocation.value = to;
		}
		return {
			location: currentLocation,
			state: historyState,
			push,
			replace
		};
	}
	/**
	* Creates an HTML5 history. Most common history for single page applications.
	*
	* @param base -
	*/
	function createWebHistory(base) {
		base = normalizeBase(base);
		const historyNavigation = useHistoryStateNavigation(base);
		const historyListeners = useHistoryListeners(base, historyNavigation.state, historyNavigation.location, historyNavigation.replace);
		function go(delta, triggerListeners = true) {
			if (!triggerListeners) historyListeners.pauseListeners();
			history.go(delta);
		}
		const routerHistory = assign({
			location: "",
			base,
			go,
			createHref: createHref.bind(null, base)
		}, historyNavigation, historyListeners);
		Object.defineProperty(routerHistory, "location", {
			enumerable: true,
			get: () => historyNavigation.location.value
		});
		Object.defineProperty(routerHistory, "state", {
			enumerable: true,
			get: () => historyNavigation.state.value
		});
		return routerHistory;
	}
	var TokenType = /* @__PURE__ */ function(TokenType$1) {
		TokenType$1[TokenType$1["Static"] = 0] = "Static";
		TokenType$1[TokenType$1["Param"] = 1] = "Param";
		TokenType$1[TokenType$1["Group"] = 2] = "Group";
		return TokenType$1;
	}({});
	var TokenizerState = /* @__PURE__ */ function(TokenizerState$1) {
		TokenizerState$1[TokenizerState$1["Static"] = 0] = "Static";
		TokenizerState$1[TokenizerState$1["Param"] = 1] = "Param";
		TokenizerState$1[TokenizerState$1["ParamRegExp"] = 2] = "ParamRegExp";
		TokenizerState$1[TokenizerState$1["ParamRegExpEnd"] = 3] = "ParamRegExpEnd";
		TokenizerState$1[TokenizerState$1["EscapeNext"] = 4] = "EscapeNext";
		return TokenizerState$1;
	}(TokenizerState || {});
	var ROOT_TOKEN = {
		type: TokenType.Static,
		value: ""
	};
	var VALID_PARAM_RE = /[a-zA-Z0-9_]/;
	function tokenizePath(path) {
		if (!path) return [[]];
		if (path === "/") return [[ROOT_TOKEN]];
		if (!path.startsWith("/")) throw new Error(`Invalid path "${path}"`);
		function crash(message) {
			throw new Error(`ERR (${state})/"${buffer}": ${message}`);
		}
		let state = TokenizerState.Static;
		let previousState = state;
		const tokens = [];
		let segment;
		function finalizeSegment() {
			if (segment) tokens.push(segment);
			segment = [];
		}
		let i = 0;
		let char;
		let buffer = "";
		let customRe = "";
		function consumeBuffer() {
			if (!buffer) return;
			if (state === TokenizerState.Static) segment.push({
				type: TokenType.Static,
				value: buffer
			});
			else if (state === TokenizerState.Param || state === TokenizerState.ParamRegExp || state === TokenizerState.ParamRegExpEnd) {
				if (segment.length > 1 && (char === "*" || char === "+")) crash(`A repeatable param (${buffer}) must be alone in its segment. eg: '/:ids+.`);
				segment.push({
					type: TokenType.Param,
					value: buffer,
					regexp: customRe,
					repeatable: char === "*" || char === "+",
					optional: char === "*" || char === "?"
				});
			} else crash("Invalid state to consume buffer");
			buffer = "";
		}
		function addCharToBuffer() {
			buffer += char;
		}
		while (i < path.length) {
			char = path[i++];
			if (char === "\\" && state !== TokenizerState.ParamRegExp) {
				previousState = state;
				state = TokenizerState.EscapeNext;
				continue;
			}
			switch (state) {
				case TokenizerState.Static:
					if (char === "/") {
						if (buffer) consumeBuffer();
						finalizeSegment();
					} else if (char === ":") {
						consumeBuffer();
						state = TokenizerState.Param;
					} else addCharToBuffer();
					break;
				case TokenizerState.EscapeNext:
					addCharToBuffer();
					state = previousState;
					break;
				case TokenizerState.Param:
					if (char === "(") state = TokenizerState.ParamRegExp;
					else if (VALID_PARAM_RE.test(char)) addCharToBuffer();
					else {
						consumeBuffer();
						state = TokenizerState.Static;
						if (char !== "*" && char !== "?" && char !== "+") i--;
					}
					break;
				case TokenizerState.ParamRegExp:
					if (char === ")") if (customRe[customRe.length - 1] == "\\") customRe = customRe.slice(0, -1) + char;
					else state = TokenizerState.ParamRegExpEnd;
					else customRe += char;
					break;
				case TokenizerState.ParamRegExpEnd:
					consumeBuffer();
					state = TokenizerState.Static;
					if (char !== "*" && char !== "?" && char !== "+") i--;
					customRe = "";
					break;
				default: crash("Unknown state");
			}
		}
		if (state === TokenizerState.ParamRegExp) crash(`Unfinished custom RegExp for param "${buffer}"`);
		consumeBuffer();
		finalizeSegment();
		return tokens;
	}
	var BASE_PARAM_PATTERN = "[^/]+?";
	var BASE_PATH_PARSER_OPTIONS = {
		sensitive: false,
		strict: false,
		start: true,
		end: true
	};
	var PathScore = /* @__PURE__ */ function(PathScore$1) {
		PathScore$1[PathScore$1["_multiplier"] = 10] = "_multiplier";
		PathScore$1[PathScore$1["Root"] = 90] = "Root";
		PathScore$1[PathScore$1["Segment"] = 40] = "Segment";
		PathScore$1[PathScore$1["SubSegment"] = 30] = "SubSegment";
		PathScore$1[PathScore$1["Static"] = 40] = "Static";
		PathScore$1[PathScore$1["Dynamic"] = 20] = "Dynamic";
		PathScore$1[PathScore$1["BonusCustomRegExp"] = 10] = "BonusCustomRegExp";
		PathScore$1[PathScore$1["BonusWildcard"] = -50] = "BonusWildcard";
		PathScore$1[PathScore$1["BonusRepeatable"] = -20] = "BonusRepeatable";
		PathScore$1[PathScore$1["BonusOptional"] = -8] = "BonusOptional";
		PathScore$1[PathScore$1["BonusStrict"] = .7000000000000001] = "BonusStrict";
		PathScore$1[PathScore$1["BonusCaseSensitive"] = .25] = "BonusCaseSensitive";
		return PathScore$1;
	}(PathScore || {});
	var REGEX_CHARS_RE = /[.+*?^${}()[\]/\\]/g;
	/**
	* Creates a path parser from an array of Segments (a segment is an array of Tokens)
	*
	* @param segments - array of segments returned by tokenizePath
	* @param extraOptions - optional options for the regexp
	* @returns a PathParser
	*/
	function tokensToParser(segments, extraOptions) {
		const options = assign({}, BASE_PATH_PARSER_OPTIONS, extraOptions);
		const score = [];
		let pattern = options.start ? "^" : "";
		const keys = [];
		for (const segment of segments) {
			const segmentScores = segment.length ? [] : [PathScore.Root];
			if (options.strict && !segment.length) pattern += "/";
			for (let tokenIndex = 0; tokenIndex < segment.length; tokenIndex++) {
				const token = segment[tokenIndex];
				let subSegmentScore = PathScore.Segment + (options.sensitive ? PathScore.BonusCaseSensitive : 0);
				if (token.type === TokenType.Static) {
					if (!tokenIndex) pattern += "/";
					pattern += token.value.replace(REGEX_CHARS_RE, "\\$&");
					subSegmentScore += PathScore.Static;
				} else if (token.type === TokenType.Param) {
					const { value, repeatable, optional, regexp } = token;
					keys.push({
						name: value,
						repeatable,
						optional
					});
					const re$1 = regexp ? regexp : BASE_PARAM_PATTERN;
					if (re$1 !== BASE_PARAM_PATTERN) {
						subSegmentScore += PathScore.BonusCustomRegExp;
						try {
							`${re$1}`;
						} catch (err) {
							throw new Error(`Invalid custom RegExp for param "${value}" (${re$1}): ` + err.message);
						}
					}
					let subPattern = repeatable ? `((?:${re$1})(?:/(?:${re$1}))*)` : `(${re$1})`;
					if (!tokenIndex) subPattern = optional && segment.length < 2 ? `(?:/${subPattern})` : "/" + subPattern;
					if (optional) subPattern += "?";
					pattern += subPattern;
					subSegmentScore += PathScore.Dynamic;
					if (optional) subSegmentScore += PathScore.BonusOptional;
					if (repeatable) subSegmentScore += PathScore.BonusRepeatable;
					if (re$1 === ".*") subSegmentScore += PathScore.BonusWildcard;
				}
				segmentScores.push(subSegmentScore);
			}
			score.push(segmentScores);
		}
		if (options.strict && options.end) {
			const i = score.length - 1;
			score[i][score[i].length - 1] += PathScore.BonusStrict;
		}
		if (!options.strict) pattern += "/?";
		if (options.end) pattern += "$";
		else if (options.strict && !pattern.endsWith("/")) pattern += "(?:/|$)";
		const re = new RegExp(pattern, options.sensitive ? "" : "i");
		function parse(path) {
			const match = path.match(re);
			const params = {};
			if (!match) return null;
			for (let i = 1; i < match.length; i++) {
				const value = match[i] || "";
				const key = keys[i - 1];
				params[key.name] = value && key.repeatable ? value.split("/") : value;
			}
			return params;
		}
		function stringify(params) {
			let path = "";
			let avoidDuplicatedSlash = false;
			for (const segment of segments) {
				if (!avoidDuplicatedSlash || !path.endsWith("/")) path += "/";
				avoidDuplicatedSlash = false;
				for (const token of segment) if (token.type === TokenType.Static) path += token.value;
				else if (token.type === TokenType.Param) {
					const { value, repeatable, optional } = token;
					const param = value in params ? params[value] : "";
					if (isArray(param) && !repeatable) throw new Error(`Provided param "${value}" is an array but it is not repeatable (* or + modifiers)`);
					const text = isArray(param) ? param.join("/") : param;
					if (!text) if (optional) {
						if (segment.length < 2) if (path.endsWith("/")) path = path.slice(0, -1);
						else avoidDuplicatedSlash = true;
					} else throw new Error(`Missing required param "${value}"`);
					path += text;
				}
			}
			return path || "/";
		}
		return {
			re,
			score,
			keys,
			parse,
			stringify
		};
	}
	/**
	* Compares an array of numbers as used in PathParser.score and returns a
	* number. This function can be used to `sort` an array
	*
	* @param a - first array of numbers
	* @param b - second array of numbers
	* @returns 0 if both are equal, < 0 if a should be sorted first, > 0 if b
	* should be sorted first
	*/
	function compareScoreArray(a, b) {
		let i = 0;
		while (i < a.length && i < b.length) {
			const diff = b[i] - a[i];
			if (diff) return diff;
			i++;
		}
		if (a.length < b.length) return a.length === 1 && a[0] === PathScore.Static + PathScore.Segment ? -1 : 1;
		else if (a.length > b.length) return b.length === 1 && b[0] === PathScore.Static + PathScore.Segment ? 1 : -1;
		return 0;
	}
	/**
	* Compare function that can be used with `sort` to sort an array of PathParser
	*
	* @param a - first PathParser
	* @param b - second PathParser
	* @returns 0 if both are equal, < 0 if a should be sorted first, > 0 if b
	*/
	function comparePathParserScore(a, b) {
		let i = 0;
		const aScore = a.score;
		const bScore = b.score;
		while (i < aScore.length && i < bScore.length) {
			const comp = compareScoreArray(aScore[i], bScore[i]);
			if (comp) return comp;
			i++;
		}
		if (Math.abs(bScore.length - aScore.length) === 1) {
			if (isLastScoreNegative(aScore)) return 1;
			if (isLastScoreNegative(bScore)) return -1;
		}
		return bScore.length - aScore.length;
	}
	/**
	* This allows detecting splats at the end of a path: /home/:id(.*)*
	*
	* @param score - score to check
	* @returns true if the last entry is negative
	*/
	function isLastScoreNegative(score) {
		const last = score[score.length - 1];
		return score.length > 0 && last[last.length - 1] < 0;
	}
	var PATH_PARSER_OPTIONS_DEFAULTS = {
		strict: false,
		end: true,
		sensitive: false
	};
	function createRouteRecordMatcher(record, parent, options) {
		const matcher = assign(tokensToParser(tokenizePath(record.path), options), {
			record,
			parent,
			children: [],
			alias: []
		});
		if (parent) {
			if (!matcher.record.aliasOf === !parent.record.aliasOf) parent.children.push(matcher);
		}
		return matcher;
	}
	/**
	* Creates a Router Matcher.
	*
	* @internal
	* @param routes - array of initial routes
	* @param globalOptions - global route options
	*/
	function createRouterMatcher(routes, globalOptions) {
		const matchers = [];
		const matcherMap = /* @__PURE__ */ new Map();
		globalOptions = mergeOptions(PATH_PARSER_OPTIONS_DEFAULTS, globalOptions);
		function getRecordMatcher(name) {
			return matcherMap.get(name);
		}
		function addRoute(record, parent, originalRecord) {
			const isRootAdd = !originalRecord;
			const mainNormalizedRecord = normalizeRouteRecord(record);
			mainNormalizedRecord.aliasOf = originalRecord && originalRecord.record;
			const options = mergeOptions(globalOptions, record);
			const normalizedRecords = [mainNormalizedRecord];
			if ("alias" in record) {
				const aliases = typeof record.alias === "string" ? [record.alias] : record.alias;
				for (const alias of aliases) normalizedRecords.push(normalizeRouteRecord(assign({}, mainNormalizedRecord, {
					components: originalRecord ? originalRecord.record.components : mainNormalizedRecord.components,
					path: alias,
					aliasOf: originalRecord ? originalRecord.record : mainNormalizedRecord
				})));
			}
			let matcher;
			let originalMatcher;
			for (const normalizedRecord of normalizedRecords) {
				const { path } = normalizedRecord;
				if (parent && path[0] !== "/") {
					const parentPath = parent.record.path;
					const connectingSlash = parentPath[parentPath.length - 1] === "/" ? "" : "/";
					normalizedRecord.path = parent.record.path + (path && connectingSlash + path);
				}
				matcher = createRouteRecordMatcher(normalizedRecord, parent, options);
				if (originalRecord) originalRecord.alias.push(matcher);
				else {
					originalMatcher = originalMatcher || matcher;
					if (originalMatcher !== matcher) originalMatcher.alias.push(matcher);
					if (isRootAdd && record.name && !isAliasRecord(matcher)) removeRoute(record.name);
				}
				if (isMatchable(matcher)) insertMatcher(matcher);
				if (mainNormalizedRecord.children) {
					const children = mainNormalizedRecord.children;
					for (let i = 0; i < children.length; i++) addRoute(children[i], matcher, originalRecord && originalRecord.children[i]);
				}
				originalRecord = originalRecord || matcher;
			}
			return originalMatcher ? () => {
				removeRoute(originalMatcher);
			} : noop;
		}
		function removeRoute(matcherRef) {
			if (isRouteName(matcherRef)) {
				const matcher = matcherMap.get(matcherRef);
				if (matcher) {
					matcherMap.delete(matcherRef);
					matchers.splice(matchers.indexOf(matcher), 1);
					matcher.children.forEach(removeRoute);
					matcher.alias.forEach(removeRoute);
				}
			} else {
				const index = matchers.indexOf(matcherRef);
				if (index > -1) {
					matchers.splice(index, 1);
					if (matcherRef.record.name) matcherMap.delete(matcherRef.record.name);
					matcherRef.children.forEach(removeRoute);
					matcherRef.alias.forEach(removeRoute);
				}
			}
		}
		function getRoutes() {
			return matchers;
		}
		function insertMatcher(matcher) {
			const index = findInsertionIndex(matcher, matchers);
			matchers.splice(index, 0, matcher);
			if (matcher.record.name && !isAliasRecord(matcher)) matcherMap.set(matcher.record.name, matcher);
		}
		function resolve(location$1, currentLocation) {
			let matcher;
			let params = {};
			let path;
			let name;
			if ("name" in location$1 && location$1.name) {
				matcher = matcherMap.get(location$1.name);
				if (!matcher) throw createRouterError(ErrorTypes.MATCHER_NOT_FOUND, { location: location$1 });
				name = matcher.record.name;
				params = assign(pickParams(currentLocation.params, matcher.keys.filter((k) => !k.optional).concat(matcher.parent ? matcher.parent.keys.filter((k) => k.optional) : []).map((k) => k.name)), location$1.params && pickParams(location$1.params, matcher.keys.map((k) => k.name)));
				path = matcher.stringify(params);
			} else if (location$1.path != null) {
				path = location$1.path;
				matcher = matchers.find((m) => m.re.test(path));
				if (matcher) {
					params = matcher.parse(path);
					name = matcher.record.name;
				}
			} else {
				matcher = currentLocation.name ? matcherMap.get(currentLocation.name) : matchers.find((m) => m.re.test(currentLocation.path));
				if (!matcher) throw createRouterError(ErrorTypes.MATCHER_NOT_FOUND, {
					location: location$1,
					currentLocation
				});
				name = matcher.record.name;
				params = assign({}, currentLocation.params, location$1.params);
				path = matcher.stringify(params);
			}
			const matched = [];
			let parentMatcher = matcher;
			while (parentMatcher) {
				matched.unshift(parentMatcher.record);
				parentMatcher = parentMatcher.parent;
			}
			return {
				name,
				path,
				params,
				matched,
				meta: mergeMetaFields(matched)
			};
		}
		routes.forEach((route) => addRoute(route));
		function clearRoutes() {
			matchers.length = 0;
			matcherMap.clear();
		}
		return {
			addRoute,
			resolve,
			removeRoute,
			clearRoutes,
			getRoutes,
			getRecordMatcher
		};
	}
	/**
	* Picks an object param to contain only specified keys.
	*
	* @param params - params object to pick from
	* @param keys - keys to pick
	*/
	function pickParams(params, keys) {
		const newParams = {};
		for (const key of keys) if (key in params) newParams[key] = params[key];
		return newParams;
	}
	/**
	* Normalizes a RouteRecordRaw. Creates a copy
	*
	* @param record
	* @returns the normalized version
	*/
	function normalizeRouteRecord(record) {
		const normalized = {
			path: record.path,
			redirect: record.redirect,
			name: record.name,
			meta: record.meta || {},
			aliasOf: record.aliasOf,
			beforeEnter: record.beforeEnter,
			props: normalizeRecordProps(record),
			children: record.children || [],
			instances: {},
			leaveGuards: /* @__PURE__ */ new Set(),
			updateGuards: /* @__PURE__ */ new Set(),
			enterCallbacks: {},
			components: "components" in record ? record.components || null : record.component && { default: record.component }
		};
		Object.defineProperty(normalized, "mods", { value: {} });
		return normalized;
	}
	/**
	* Normalize the optional `props` in a record to always be an object similar to
	* components. Also accept a boolean for components.
	* @param record
	*/
	function normalizeRecordProps(record) {
		const propsObject = {};
		const props = record.props || false;
		if ("component" in record) propsObject.default = props;
		else for (const name in record.components) propsObject[name] = typeof props === "object" ? props[name] : props;
		return propsObject;
	}
	/**
	* Checks if a record or any of its parent is an alias
	* @param record
	*/
	function isAliasRecord(record) {
		while (record) {
			if (record.record.aliasOf) return true;
			record = record.parent;
		}
		return false;
	}
	/**
	* Merge meta fields of an array of records
	*
	* @param matched - array of matched records
	*/
	function mergeMetaFields(matched) {
		return matched.reduce((meta, record) => assign(meta, record.meta), {});
	}
	/**
	* Performs a binary search to find the correct insertion index for a new matcher.
	*
	* Matchers are primarily sorted by their score. If scores are tied then we also consider parent/child relationships,
	* with descendants coming before ancestors. If there's still a tie, new routes are inserted after existing routes.
	*
	* @param matcher - new matcher to be inserted
	* @param matchers - existing matchers
	*/
	function findInsertionIndex(matcher, matchers) {
		let lower = 0;
		let upper = matchers.length;
		while (lower !== upper) {
			const mid = lower + upper >> 1;
			if (comparePathParserScore(matcher, matchers[mid]) < 0) upper = mid;
			else lower = mid + 1;
		}
		const insertionAncestor = getInsertionAncestor(matcher);
		if (insertionAncestor) upper = matchers.lastIndexOf(insertionAncestor, upper - 1);
		return upper;
	}
	function getInsertionAncestor(matcher) {
		let ancestor = matcher;
		while (ancestor = ancestor.parent) if (isMatchable(ancestor) && comparePathParserScore(matcher, ancestor) === 0) return ancestor;
	}
	/**
	* Checks if a matcher can be reachable. This means if it's possible to reach it as a route. For example, routes without
	* a component, or name, or redirect, are just used to group other routes.
	* @param matcher
	* @param matcher.record record of the matcher
	* @returns
	*/
	function isMatchable({ record }) {
		return !!(record.name || record.components && Object.keys(record.components).length || record.redirect);
	}
	/**
	* Returns the internal behavior of a {@link RouterLink} without the rendering part.
	*
	* @param props - a `to` location and an optional `replace` flag
	*/
	function useLink(props) {
		const router = inject(routerKey);
		const currentRoute = inject(routeLocationKey);
		const route = computed(() => {
			const to = unref(props.to);
			return router.resolve(to);
		});
		const activeRecordIndex = computed(() => {
			const { matched } = route.value;
			const { length } = matched;
			const routeMatched = matched[length - 1];
			const currentMatched = currentRoute.matched;
			if (!routeMatched || !currentMatched.length) return -1;
			const index = currentMatched.findIndex(isSameRouteRecord.bind(null, routeMatched));
			if (index > -1) return index;
			const parentRecordPath = getOriginalPath(matched[length - 2]);
			return length > 1 && getOriginalPath(routeMatched) === parentRecordPath && currentMatched[currentMatched.length - 1].path !== parentRecordPath ? currentMatched.findIndex(isSameRouteRecord.bind(null, matched[length - 2])) : index;
		});
		const isActive = computed(() => activeRecordIndex.value > -1 && includesParams(currentRoute.params, route.value.params));
		const isExactActive = computed(() => activeRecordIndex.value > -1 && activeRecordIndex.value === currentRoute.matched.length - 1 && isSameRouteLocationParams(currentRoute.params, route.value.params));
		function navigate(e = {}) {
			if (guardEvent(e)) {
				const p = router[unref(props.replace) ? "replace" : "push"](unref(props.to)).catch(noop);
				if (props.viewTransition && typeof document !== "undefined" && "startViewTransition" in document) document.startViewTransition(() => p);
				return p;
			}
			return Promise.resolve();
		}
		/**
		* NOTE: update {@link _RouterLinkI}'s `$slots` type when updating this
		*/
		return {
			route,
			href: computed(() => route.value.href),
			isActive,
			isExactActive,
			navigate
		};
	}
	function preferSingleVNode(vnodes) {
		return vnodes.length === 1 ? vnodes[0] : vnodes;
	}
	/**
	* Component to render a link that triggers a navigation on click.
	*/
	var RouterLink = /* @__PURE__ */ defineComponent({
		name: "RouterLink",
		compatConfig: { MODE: 3 },
		props: {
			to: {
				type: [String, Object],
				required: true
			},
			replace: Boolean,
			activeClass: String,
			exactActiveClass: String,
			custom: Boolean,
			ariaCurrentValue: {
				type: String,
				default: "page"
			},
			viewTransition: Boolean
		},
		useLink,
		setup(props, { slots }) {
			const link = /* @__PURE__ */ reactive(useLink(props));
			const { options } = inject(routerKey);
			const elClass = computed(() => ({
				[getLinkClass(props.activeClass, options.linkActiveClass, "router-link-active")]: link.isActive,
				[getLinkClass(props.exactActiveClass, options.linkExactActiveClass, "router-link-exact-active")]: link.isExactActive
			}));
			return () => {
				const children = slots.default && preferSingleVNode(slots.default(link));
				return props.custom ? children : h("a", {
					"aria-current": link.isExactActive ? props.ariaCurrentValue : null,
					href: link.href,
					onClick: link.navigate,
					class: elClass.value
				}, children);
			};
		}
	});
	function guardEvent(e) {
		if (e.metaKey || e.altKey || e.ctrlKey || e.shiftKey) return;
		if (e.defaultPrevented) return;
		if (e.button !== void 0 && e.button !== 0) return;
		if (e.currentTarget && e.currentTarget.getAttribute) {
			const target = e.currentTarget.getAttribute("target");
			if (/\b_blank\b/i.test(target)) return;
		}
		if (e.preventDefault) e.preventDefault();
		return true;
	}
	function includesParams(outer, inner) {
		for (const key in inner) {
			const innerValue = inner[key];
			const outerValue = outer[key];
			if (typeof innerValue === "string") {
				if (innerValue !== outerValue) return false;
			} else if (!isArray(outerValue) || outerValue.length !== innerValue.length || innerValue.some((value, i) => value.valueOf() !== outerValue[i].valueOf())) return false;
		}
		return true;
	}
	/**
	* Get the original path value of a record by following its aliasOf
	* @param record
	*/
	function getOriginalPath(record) {
		return record ? record.aliasOf ? record.aliasOf.path : record.path : "";
	}
	/**
	* Utility class to get the active class based on defaults.
	* @param propClass
	* @param globalClass
	* @param defaultClass
	*/
	var getLinkClass = (propClass, globalClass, defaultClass) => propClass != null ? propClass : globalClass != null ? globalClass : defaultClass;
	var RouterViewImpl = /* @__PURE__ */ defineComponent({
		name: "RouterView",
		inheritAttrs: false,
		props: {
			name: {
				type: String,
				default: "default"
			},
			route: Object
		},
		compatConfig: { MODE: 3 },
		setup(props, { attrs, slots }) {
			const injectedRoute = inject(routerViewLocationKey);
			const routeToDisplay = computed(() => props.route || injectedRoute.value);
			const injectedDepth = inject(viewDepthKey, 0);
			const depth = computed(() => {
				let initialDepth = unref(injectedDepth);
				const { matched } = routeToDisplay.value;
				let matchedRoute;
				while ((matchedRoute = matched[initialDepth]) && !matchedRoute.components) initialDepth++;
				return initialDepth;
			});
			const matchedRouteRef = computed(() => routeToDisplay.value.matched[depth.value]);
			provide(viewDepthKey, computed(() => depth.value + 1));
			provide(matchedRouteKey, matchedRouteRef);
			provide(routerViewLocationKey, routeToDisplay);
			const viewRef = /* @__PURE__ */ ref();
			watch(() => [
				viewRef.value,
				matchedRouteRef.value,
				props.name
			], ([instance, to, name], [oldInstance, from, oldName]) => {
				if (to) {
					to.instances[name] = instance;
					if (from && from !== to && instance && instance === oldInstance) {
						if (!to.leaveGuards.size) to.leaveGuards = from.leaveGuards;
						if (!to.updateGuards.size) to.updateGuards = from.updateGuards;
					}
				}
				if (instance && to && (!from || !isSameRouteRecord(to, from) || !oldInstance)) (to.enterCallbacks[name] || []).forEach((callback) => callback(instance));
			}, { flush: "post" });
			return () => {
				const route = routeToDisplay.value;
				const currentName = props.name;
				const matchedRoute = matchedRouteRef.value;
				const ViewComponent = matchedRoute && matchedRoute.components[currentName];
				if (!ViewComponent) return normalizeSlot(slots.default, {
					Component: ViewComponent,
					route
				});
				const routePropsOption = matchedRoute.props[currentName];
				const routeProps = routePropsOption ? routePropsOption === true ? route.params : typeof routePropsOption === "function" ? routePropsOption(route) : routePropsOption : null;
				const onVnodeUnmounted = (vnode) => {
					if (vnode.component.isUnmounted) matchedRoute.instances[currentName] = null;
				};
				const component = h(ViewComponent, assign({}, routeProps, attrs, {
					onVnodeUnmounted,
					ref: viewRef
				}));
				return normalizeSlot(slots.default, {
					Component: component,
					route
				}) || component;
			};
		}
	});
	function normalizeSlot(slot, data) {
		if (!slot) return null;
		const slotContent = slot(data);
		return slotContent.length === 1 ? slotContent[0] : slotContent;
	}
	/**
	* Component to display the current route the user is at.
	*/
	var RouterView = RouterViewImpl;
	/**
	* Creates a Router instance that can be used by a Vue app.
	*
	* @param options - {@link RouterOptions}
	*/
	function createRouter(options) {
		const matcher = createRouterMatcher(options.routes, options);
		const parseQuery$1 = options.parseQuery || parseQuery;
		const stringifyQuery$1 = options.stringifyQuery || stringifyQuery;
		const routerHistory = options.history;
		const beforeGuards = useCallbacks();
		const beforeResolveGuards = useCallbacks();
		const afterGuards = useCallbacks();
		const currentRoute = /* @__PURE__ */ shallowRef(START_LOCATION_NORMALIZED);
		let pendingLocation = START_LOCATION_NORMALIZED;
		if (isBrowser && options.scrollBehavior && "scrollRestoration" in history) history.scrollRestoration = "manual";
		const normalizeParams = applyToParams.bind(null, (paramValue) => "" + paramValue);
		const encodeParams = applyToParams.bind(null, encodeParam);
		const decodeParams = applyToParams.bind(null, decode);
		function addRoute(parentOrRoute, route) {
			let parent;
			let record;
			if (isRouteName(parentOrRoute)) {
				parent = matcher.getRecordMatcher(parentOrRoute);
				record = route;
			} else record = parentOrRoute;
			return matcher.addRoute(record, parent);
		}
		function removeRoute(name) {
			const recordMatcher = matcher.getRecordMatcher(name);
			if (recordMatcher) matcher.removeRoute(recordMatcher);
		}
		function getRoutes() {
			return matcher.getRoutes().map((routeMatcher) => routeMatcher.record);
		}
		function hasRoute(name) {
			return !!matcher.getRecordMatcher(name);
		}
		function resolve(rawLocation, currentLocation) {
			currentLocation = assign({}, currentLocation || currentRoute.value);
			if (typeof rawLocation === "string") {
				const locationNormalized = parseURL(parseQuery$1, rawLocation, currentLocation.path);
				const matchedRoute$1 = matcher.resolve({ path: locationNormalized.path }, currentLocation);
				const href$1 = routerHistory.createHref(locationNormalized.fullPath);
				return assign(locationNormalized, matchedRoute$1, {
					params: decodeParams(matchedRoute$1.params),
					hash: decode(locationNormalized.hash),
					redirectedFrom: void 0,
					href: href$1
				});
			}
			let matcherLocation;
			if (rawLocation.path != null) matcherLocation = assign({}, rawLocation, { path: parseURL(parseQuery$1, rawLocation.path, currentLocation.path).path });
			else {
				const targetParams = assign({}, rawLocation.params);
				for (const key in targetParams) if (targetParams[key] == null) delete targetParams[key];
				matcherLocation = assign({}, rawLocation, { params: encodeParams(targetParams) });
				currentLocation.params = encodeParams(currentLocation.params);
			}
			const matchedRoute = matcher.resolve(matcherLocation, currentLocation);
			const hash = rawLocation.hash || "";
			matchedRoute.params = normalizeParams(decodeParams(matchedRoute.params));
			const fullPath = stringifyURL(stringifyQuery$1, assign({}, rawLocation, {
				hash: encodeHash(hash),
				path: matchedRoute.path
			}));
			const href = routerHistory.createHref(fullPath);
			return assign({
				fullPath,
				hash,
				query: stringifyQuery$1 === stringifyQuery ? normalizeQuery(rawLocation.query) : rawLocation.query || {}
			}, matchedRoute, {
				redirectedFrom: void 0,
				href
			});
		}
		function locationAsObject(to) {
			return typeof to === "string" ? parseURL(parseQuery$1, to, currentRoute.value.path) : assign({}, to);
		}
		function checkCanceledNavigation(to, from) {
			if (pendingLocation !== to) return createRouterError(ErrorTypes.NAVIGATION_CANCELLED, {
				from,
				to
			});
		}
		function push(to) {
			return pushWithRedirect(to);
		}
		function replace(to) {
			return push(assign(locationAsObject(to), { replace: true }));
		}
		function handleRedirectRecord(to, from) {
			const lastMatched = to.matched[to.matched.length - 1];
			if (lastMatched && lastMatched.redirect) {
				const { redirect } = lastMatched;
				let newTargetLocation = typeof redirect === "function" ? redirect(to, from) : redirect;
				if (typeof newTargetLocation === "string") {
					newTargetLocation = newTargetLocation.includes("?") || newTargetLocation.includes("#") ? newTargetLocation = locationAsObject(newTargetLocation) : { path: newTargetLocation };
					newTargetLocation.params = {};
				}
				return assign({
					query: to.query,
					hash: to.hash,
					params: newTargetLocation.path != null ? {} : to.params
				}, newTargetLocation);
			}
		}
		function pushWithRedirect(to, redirectedFrom) {
			const targetLocation = pendingLocation = resolve(to);
			const from = currentRoute.value;
			const data = to.state;
			const force = to.force;
			const replace$1 = to.replace === true;
			const shouldRedirect = handleRedirectRecord(targetLocation, from);
			if (shouldRedirect) return pushWithRedirect(assign(locationAsObject(shouldRedirect), {
				state: typeof shouldRedirect === "object" ? assign({}, data, shouldRedirect.state) : data,
				force,
				replace: replace$1
			}), redirectedFrom || targetLocation);
			const toLocation = targetLocation;
			toLocation.redirectedFrom = redirectedFrom;
			let failure;
			if (!force && isSameRouteLocation(stringifyQuery$1, from, targetLocation)) {
				failure = createRouterError(ErrorTypes.NAVIGATION_DUPLICATED, {
					to: toLocation,
					from
				});
				handleScroll(from, from, true, false);
			}
			return (failure ? Promise.resolve(failure) : navigate(toLocation, from)).catch((error) => isNavigationFailure(error) ? isNavigationFailure(error, ErrorTypes.NAVIGATION_GUARD_REDIRECT) ? error : markAsReady(error) : triggerError(error, toLocation, from)).then((failure$1) => {
				if (failure$1) {
					if (isNavigationFailure(failure$1, ErrorTypes.NAVIGATION_GUARD_REDIRECT)) return pushWithRedirect(assign({ replace: replace$1 }, locationAsObject(failure$1.to), {
						state: typeof failure$1.to === "object" ? assign({}, data, failure$1.to.state) : data,
						force
					}), redirectedFrom || toLocation);
				} else failure$1 = finalizeNavigation(toLocation, from, true, replace$1, data);
				triggerAfterEach(toLocation, from, failure$1);
				return failure$1;
			});
		}
		/**
		* Helper to reject and skip all navigation guards if a new navigation happened
		* @param to
		* @param from
		*/
		function checkCanceledNavigationAndReject(to, from) {
			const error = checkCanceledNavigation(to, from);
			return error ? Promise.reject(error) : Promise.resolve();
		}
		function runWithContext(fn) {
			const app = installedApps.values().next().value;
			return app && typeof app.runWithContext === "function" ? app.runWithContext(fn) : fn();
		}
		function navigate(to, from) {
			let guards;
			const [leavingRecords, updatingRecords, enteringRecords] = extractChangingRecords(to, from);
			guards = extractComponentsGuards(leavingRecords.reverse(), "beforeRouteLeave", to, from);
			for (const record of leavingRecords) record.leaveGuards.forEach((guard) => {
				guards.push(guardToPromiseFn(guard, to, from));
			});
			const canceledNavigationCheck = checkCanceledNavigationAndReject.bind(null, to, from);
			guards.push(canceledNavigationCheck);
			return runGuardQueue(guards).then(() => {
				guards = [];
				for (const guard of beforeGuards.list()) guards.push(guardToPromiseFn(guard, to, from));
				guards.push(canceledNavigationCheck);
				return runGuardQueue(guards);
			}).then(() => {
				guards = extractComponentsGuards(updatingRecords, "beforeRouteUpdate", to, from);
				for (const record of updatingRecords) record.updateGuards.forEach((guard) => {
					guards.push(guardToPromiseFn(guard, to, from));
				});
				guards.push(canceledNavigationCheck);
				return runGuardQueue(guards);
			}).then(() => {
				guards = [];
				for (const record of enteringRecords) if (record.beforeEnter) if (isArray(record.beforeEnter)) for (const beforeEnter of record.beforeEnter) guards.push(guardToPromiseFn(beforeEnter, to, from));
				else guards.push(guardToPromiseFn(record.beforeEnter, to, from));
				guards.push(canceledNavigationCheck);
				return runGuardQueue(guards);
			}).then(() => {
				to.matched.forEach((record) => record.enterCallbacks = {});
				guards = extractComponentsGuards(enteringRecords, "beforeRouteEnter", to, from, runWithContext);
				guards.push(canceledNavigationCheck);
				return runGuardQueue(guards);
			}).then(() => {
				guards = [];
				for (const guard of beforeResolveGuards.list()) guards.push(guardToPromiseFn(guard, to, from));
				guards.push(canceledNavigationCheck);
				return runGuardQueue(guards);
			}).catch((err) => isNavigationFailure(err, ErrorTypes.NAVIGATION_CANCELLED) ? err : Promise.reject(err));
		}
		function triggerAfterEach(to, from, failure) {
			afterGuards.list().forEach((guard) => runWithContext(() => guard(to, from, failure)));
		}
		/**
		* - Cleans up any navigation guards
		* - Changes the url if necessary
		* - Calls the scrollBehavior
		*/
		function finalizeNavigation(toLocation, from, isPush, replace$1, data) {
			const error = checkCanceledNavigation(toLocation, from);
			if (error) return error;
			const isFirstNavigation = from === START_LOCATION_NORMALIZED;
			const state = !isBrowser ? {} : history.state;
			if (isPush) if (replace$1 || isFirstNavigation) routerHistory.replace(toLocation.fullPath, assign({ scroll: isFirstNavigation && state && state.scroll }, data));
			else routerHistory.push(toLocation.fullPath, data);
			currentRoute.value = toLocation;
			handleScroll(toLocation, from, isPush, isFirstNavigation);
			markAsReady();
		}
		let removeHistoryListener;
		function setupListeners() {
			if (removeHistoryListener) return;
			removeHistoryListener = routerHistory.listen((to, _from, info) => {
				if (!router.listening) return;
				const toLocation = resolve(to);
				const shouldRedirect = handleRedirectRecord(toLocation, router.currentRoute.value);
				if (shouldRedirect) {
					pushWithRedirect(assign(shouldRedirect, {
						replace: true,
						force: true
					}), toLocation).catch(noop);
					return;
				}
				pendingLocation = toLocation;
				const from = currentRoute.value;
				if (isBrowser) saveScrollPosition(getScrollKey(from.fullPath, info.delta), computeScrollPosition());
				navigate(toLocation, from).catch((error) => {
					if (isNavigationFailure(error, ErrorTypes.NAVIGATION_ABORTED | ErrorTypes.NAVIGATION_CANCELLED)) return error;
					if (isNavigationFailure(error, ErrorTypes.NAVIGATION_GUARD_REDIRECT)) {
						pushWithRedirect(assign(locationAsObject(error.to), { force: true }), toLocation).then((failure) => {
							if (isNavigationFailure(failure, ErrorTypes.NAVIGATION_ABORTED | ErrorTypes.NAVIGATION_DUPLICATED) && !info.delta && info.type === NavigationType.pop) routerHistory.go(-1, false);
						}).catch(noop);
						return Promise.reject();
					}
					if (info.delta) routerHistory.go(-info.delta, false);
					return triggerError(error, toLocation, from);
				}).then((failure) => {
					failure = failure || finalizeNavigation(toLocation, from, false);
					if (failure) {
						if (info.delta && !isNavigationFailure(failure, ErrorTypes.NAVIGATION_CANCELLED)) routerHistory.go(-info.delta, false);
						else if (info.type === NavigationType.pop && isNavigationFailure(failure, ErrorTypes.NAVIGATION_ABORTED | ErrorTypes.NAVIGATION_DUPLICATED)) routerHistory.go(-1, false);
					}
					triggerAfterEach(toLocation, from, failure);
				}).catch(noop);
			});
		}
		let readyHandlers = useCallbacks();
		let errorListeners = useCallbacks();
		let ready;
		/**
		* Trigger errorListeners added via onError and throws the error as well
		*
		* @param error - error to throw
		* @param to - location we were navigating to when the error happened
		* @param from - location we were navigating from when the error happened
		* @returns the error as a rejected promise
		*/
		function triggerError(error, to, from) {
			markAsReady(error);
			const list = errorListeners.list();
			if (list.length) list.forEach((handler) => handler(error, to, from));
			else console.error(error);
			return Promise.reject(error);
		}
		function isReady() {
			if (ready && currentRoute.value !== START_LOCATION_NORMALIZED) return Promise.resolve();
			return new Promise((resolve$1, reject) => {
				readyHandlers.add([resolve$1, reject]);
			});
		}
		function markAsReady(err) {
			if (!ready) {
				ready = !err;
				setupListeners();
				readyHandlers.list().forEach(([resolve$1, reject]) => err ? reject(err) : resolve$1());
				readyHandlers.reset();
			}
			return err;
		}
		function handleScroll(to, from, isPush, isFirstNavigation) {
			const { scrollBehavior } = options;
			if (!isBrowser || !scrollBehavior) return Promise.resolve();
			const scrollPosition = !isPush && getSavedScrollPosition(getScrollKey(to.fullPath, 0)) || (isFirstNavigation || !isPush) && history.state && history.state.scroll || null;
			return nextTick().then(() => scrollBehavior(to, from, scrollPosition)).then((position) => position && scrollToPosition(position)).catch((err) => triggerError(err, to, from));
		}
		const go = (delta) => routerHistory.go(delta);
		let started;
		const installedApps = /* @__PURE__ */ new Set();
		const router = {
			currentRoute,
			listening: true,
			addRoute,
			removeRoute,
			clearRoutes: matcher.clearRoutes,
			hasRoute,
			getRoutes,
			resolve,
			options,
			push,
			replace,
			go,
			back: () => go(-1),
			forward: () => go(1),
			beforeEach: beforeGuards.add,
			beforeResolve: beforeResolveGuards.add,
			afterEach: afterGuards.add,
			onError: errorListeners.add,
			isReady,
			install(app) {
				app.component("RouterLink", RouterLink);
				app.component("RouterView", RouterView);
				app.config.globalProperties.$router = router;
				Object.defineProperty(app.config.globalProperties, "$route", {
					enumerable: true,
					get: () => unref(currentRoute)
				});
				if (isBrowser && !started && currentRoute.value === START_LOCATION_NORMALIZED) {
					started = true;
					push(routerHistory.location).catch((err) => {});
				}
				const reactiveRoute = {};
				for (const key in START_LOCATION_NORMALIZED) Object.defineProperty(reactiveRoute, key, {
					get: () => currentRoute.value[key],
					enumerable: true
				});
				app.provide(routerKey, router);
				app.provide(routeLocationKey, /* @__PURE__ */ shallowReactive(reactiveRoute));
				app.provide(routerViewLocationKey, currentRoute);
				const unmountApp = app.unmount;
				installedApps.add(app);
				app.unmount = function() {
					installedApps.delete(app);
					if (installedApps.size < 1) {
						pendingLocation = START_LOCATION_NORMALIZED;
						removeHistoryListener && removeHistoryListener();
						removeHistoryListener = null;
						currentRoute.value = START_LOCATION_NORMALIZED;
						started = false;
						ready = false;
					}
					unmountApp();
				};
			}
		};
		function runGuardQueue(guards) {
			return guards.reduce((promise, guard) => promise.then(() => runWithContext(guard)), Promise.resolve());
		}
		return router;
	}
	/**
	* Returns the router instance. Equivalent to using `$router` inside
	* templates.
	*/
	function useRouter() {
		return inject(routerKey);
	}
	/**
	* Returns the current route location. Equivalent to using `$route` inside
	* templates.
	*/
	function useRoute(_name) {
		return inject(routeLocationKey);
	}
	//#endregion
	//#region src/app-events.ts
	var FrontendEventBus = class {
		handlers = /* @__PURE__ */ new Map();
		emit(name, payload) {
			for (const handler of this.handlers.get(name) || []) handler(payload);
		}
		on(name, handler) {
			const handlers = this.handlers.get(name) || /* @__PURE__ */ new Set();
			handlers.add(handler);
			this.handlers.set(name, handlers);
			return () => handlers.delete(handler);
		}
	};
	var appEvents = new FrontendEventBus();
	//#endregion
	//#region src/api-client.ts
	var ApiError = class extends Error {
		status;
		code;
		requestId;
		details;
		body;
		constructor(status, body) {
			const requestId = typeof body.request_id === "string" ? body.request_id : "";
			const detail = typeof body.detail === "string" ? body.detail : "";
			const message = body.message || detail || "请求失败";
			super(`${message}${requestId ? `（请求 ${requestId}）` : ""}`);
			this.name = "ApiError";
			this.status = status;
			this.code = body.code || `HTTP_${status}`;
			this.requestId = requestId;
			this.details = body.details;
			this.body = body;
		}
	};
	function normalizeApiPath(path) {
		if (path.startsWith("/api/") && !path.startsWith("/api/v1/")) return path.replace("/api/", "/api/v1/");
		return path;
	}
	function createApiClient({ fetchImpl = fetch, getCsrfToken, onUnauthorized }) {
		return { async request(path, options = {}) {
			const requestPath = normalizeApiPath(path);
			const headers = new Headers(options.headers);
			if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
			const method = (options.method || "GET").toUpperCase();
			const csrfToken = getCsrfToken();
			if (![
				"GET",
				"HEAD",
				"OPTIONS"
			].includes(method) && csrfToken) headers.set("X-CSRF-Token", csrfToken);
			const response = await fetchImpl(requestPath, {
				...options,
				headers,
				credentials: "same-origin"
			});
			const data = await response.json().catch(() => ({}));
			if (!response.ok) {
				if (response.status === 401) onUnauthorized?.(requestPath);
				throw new ApiError(response.status, data);
			}
			return data;
		} };
	}
	//#endregion
	//#region src/router.ts
	var RETURN_PATH_KEY = "ai_mm_return_path";
	function parseAppRoute(pathname) {
		if (pathname === "/" || pathname === "/login") return { name: "login" };
		if (pathname === "/register") return { name: "register" };
		if (pathname === "/cases") return { name: "case-list" };
		if (pathname === "/cases/new") return { name: "case-create" };
		const gameMatch = pathname.match(/^\/cases\/([1-9]\d*)$/);
		if (gameMatch) return {
			name: "case-detail",
			gameId: Number(gameMatch[1])
		};
		return { name: "not-found" };
	}
	function appRoutePath(route) {
		switch (route.name) {
			case "login": return "/login";
			case "register": return "/register";
			case "case-list": return "/cases";
			case "case-create": return "/cases/new";
			case "case-detail": return `/cases/${route.gameId}`;
		}
	}
	function isPrivateRoute(route) {
		return route.name === "case-list" || route.name === "case-create" || route.name === "case-detail";
	}
	function isSafeReturnPath(pathname) {
		return isPrivateRoute(parseAppRoute(pathname));
	}
	var routeRecords = [
		{
			path: "/",
			redirect: "/login"
		},
		{
			path: "/login",
			name: "login",
			component: { render: () => null }
		},
		{
			path: "/register",
			name: "register",
			component: { render: () => null }
		},
		{
			path: "/cases",
			name: "case-list",
			component: { render: () => null }
		},
		{
			path: "/cases/new",
			name: "case-create",
			component: { render: () => null }
		},
		{
			path: "/cases/:gameId(\\d+)",
			name: "case-detail",
			component: { render: () => null }
		},
		{
			path: "/:pathMatch(.*)*",
			name: "not-found",
			component: { render: () => null }
		}
	];
	function createAppRouter() {
		return createRouter({
			history: createWebHistory(),
			routes: routeRecords
		});
	}
	function createBrowserRouter(router) {
		return {
			current() {
				return parseAppRoute(window.location.pathname);
			},
			async push(route) {
				const path = appRoutePath(route);
				if (window.location.pathname !== path) await router.push(path);
			},
			async replace(route) {
				const path = appRoutePath(route);
				if (window.location.pathname !== path) await router.replace(path);
			},
			rememberCurrentReturnPath() {
				if (isSafeReturnPath(window.location.pathname)) window.sessionStorage.setItem(RETURN_PATH_KEY, window.location.pathname);
			},
			consumeReturnPath() {
				const path = window.sessionStorage.getItem(RETURN_PATH_KEY) || "";
				window.sessionStorage.removeItem(RETURN_PATH_KEY);
				return isSafeReturnPath(path) ? path : "";
			},
			clearReturnPath() {
				window.sessionStorage.removeItem(RETURN_PATH_KEY);
			},
			async replacePath(path) {
				if (isSafeReturnPath(path) && window.location.pathname !== path) await router.replace(path);
			}
		};
	}
	//#endregion
	//#region src/runtime.ts
	var apiClient = null;
	var navigation = null;
	function initializeFrontendRuntime(authStore, router) {
		navigation = createBrowserRouter(router);
		apiClient = createApiClient({
			getCsrfToken: () => authStore.csrfToken,
			onUnauthorized: (requestPath) => {
				if (requestPath.includes("/auth/login") || requestPath.includes("/auth/register")) return;
				authStore.clearSession();
				appEvents.emit("auth:logout", {
					preserveReturnPath: true,
					broadcast: false
				});
			}
		});
	}
	function getApiClient() {
		if (!apiClient) throw new Error("前端 API runtime 尚未初始化");
		return apiClient;
	}
	function getNavigation() {
		if (!navigation) throw new Error("前端 Router runtime 尚未初始化");
		return navigation;
	}
	//#endregion
	//#region src/stores/auth.ts
	var useAuthStore = defineStore("auth", {
		state: () => ({
			user: null,
			csrfToken: "",
			status: "checking",
			error: ""
		}),
		actions: {
			setSession(payload) {
				const user = "user" in payload ? payload.user : payload;
				this.user = {
					id: user.id,
					username: user.username
				};
				this.csrfToken = payload.csrf_token || this.csrfToken;
				this.status = "authenticated";
				this.error = "";
			},
			clearSession() {
				this.user = null;
				this.csrfToken = "";
				this.status = "anonymous";
				this.error = "";
			},
			async authenticate(mode, username, password) {
				this.status = "submitting";
				this.error = "";
				try {
					const result = await getApiClient().request(`/api/auth/${mode}`, {
						method: "POST",
						body: JSON.stringify({
							username: username.trim(),
							password
						})
					});
					this.setSession(result);
					appEvents.emit("auth:authenticated", { user: result.user });
				} catch (error) {
					this.status = "anonymous";
					this.error = error instanceof Error ? error.message : "认证失败";
				}
			},
			async logout() {
				this.status = "submitting";
				try {
					await getApiClient().request("/api/auth/logout", { method: "POST" });
				} catch {} finally {
					this.clearSession();
					appEvents.emit("auth:logout", {
						preserveReturnPath: false,
						broadcast: true
					});
				}
			}
		}
	});
	//#endregion
	//#region src/stores/ui.ts
	var useUiStore = defineStore("ui", {
		state: () => ({
			sidebarCollapsed: false,
			gameActive: false
		}),
		actions: {
			setSidebarCollapsed(collapsed) {
				this.sidebarCollapsed = collapsed;
			},
			setGameActive(active) {
				this.gameActive = active;
			}
		}
	});
	//#endregion
	//#region src/components/AppSidebar.vue?vue&type=script&setup=true&lang.ts
	var _hoisted_1$2 = { "aria-label": "主要导航" };
	var _hoisted_2$2 = { class: "sidebar-account" };
	var _hoisted_3$2 = ["aria-label", "title"];
	var _hoisted_4$2 = {
		id: "userAvatarInitial",
		class: "account-avatar-initial"
	};
	var _hoisted_5$2 = { id: "currentUsername" };
	var _hoisted_6$2 = ["aria-expanded"];
	var _hoisted_7$2 = ["disabled"];
	//#endregion
	//#region src/components/AppSidebar.vue
	var AppSidebar_default = /* @__PURE__ */ defineComponent({
		__name: "AppSidebar",
		setup(__props) {
			const auth = useAuthStore();
			const ui = useUiStore();
			const route = useRoute();
			const username = computed(() => auth.user?.username || "用户");
			const avatarInitial = computed(() => username.value.slice(0, 1).toUpperCase());
			const avatarStatus = computed(() => ui.gameActive ? "剧本演绎中，正在思考" : auth.user ? "在线" : "离线");
			const activeView = computed(() => {
				if (route.name === "case-list") return "records";
				if (route.name === "case-create") return "create";
				return "";
			});
			function navigate(view) {
				appEvents.emit("navigation:view", { view });
			}
			function collapseSidebar() {
				appEvents.emit("sidebar:set", {
					collapsed: true,
					focusTarget: true
				});
			}
			return (_ctx, _cache) => {
				return openBlock(), createElementBlock(Fragment, null, [
					_cache[8] || (_cache[8] = createBaseVNode("div", { class: "sidebar-brand" }, [createBaseVNode("span", { class: "brand-seal small" }, "剧"), createBaseVNode("div", null, [createBaseVNode("strong", null, "剧镜"), createBaseVNode("span", null, "悬疑推理 MVP")])], -1)),
					createBaseVNode("nav", _hoisted_1$2, [createBaseVNode("button", {
						class: normalizeClass(["nav-button", { active: activeView.value === "create" }]),
						type: "button",
						onClick: _cache[0] || (_cache[0] = ($event) => navigate("create"))
					}, [createVNode(unref(Plus), {
						size: 18,
						"aria-hidden": "true"
					}), _cache[3] || (_cache[3] = createTextVNode("新建案件", -1))], 2), createBaseVNode("button", {
						class: normalizeClass(["nav-button", { active: activeView.value === "records" }]),
						type: "button",
						onClick: _cache[1] || (_cache[1] = ($event) => navigate("records"))
					}, [createVNode(unref(Archive), {
						size: 18,
						"aria-hidden": "true"
					}), _cache[4] || (_cache[4] = createTextVNode("案件档案", -1))], 2)]),
					_cache[9] || (_cache[9] = createBaseVNode("div", { class: "mvp-scope" }, [
						createBaseVNode("span", null, "当前版本"),
						createBaseVNode("strong", null, "悬疑推理"),
						createBaseVNode("small", null, "DEDUCTION · MVP")
					], -1)),
					createBaseVNode("div", _hoisted_2$2, [
						createBaseVNode("div", {
							id: "userAvatar",
							class: normalizeClass(["avatar account-avatar", {
								"is-online": Boolean(unref(auth).user),
								"is-thinking": unref(ui).gameActive
							}]),
							role: "img",
							"aria-label": `${username.value}，${avatarStatus.value}`,
							title: `${username.value} · ${avatarStatus.value}`
						}, [
							_cache[5] || (_cache[5] = createBaseVNode("i", {
								class: "account-avatar-aura",
								"aria-hidden": "true"
							}, null, -1)),
							createBaseVNode("b", _hoisted_4$2, toDisplayString(avatarInitial.value), 1),
							_cache[6] || (_cache[6] = createBaseVNode("span", {
								class: "account-avatar-spectrum",
								"aria-hidden": "true"
							}, [
								createBaseVNode("i"),
								createBaseVNode("i"),
								createBaseVNode("i"),
								createBaseVNode("i"),
								createBaseVNode("i")
							], -1))
						], 10, _hoisted_3$2),
						createBaseVNode("div", null, [createBaseVNode("strong", _hoisted_5$2, toDisplayString(username.value), 1), _cache[7] || (_cache[7] = createBaseVNode("span", null, "本地调查员", -1))]),
						createBaseVNode("button", {
							id: "collapseSidebarBtn",
							class: "icon-button sidebar-toggle-button",
							type: "button",
							title: "隐藏导航栏",
							"aria-label": "隐藏导航栏",
							"aria-controls": "appSidebar",
							"aria-expanded": !unref(ui).sidebarCollapsed,
							onClick: collapseSidebar
						}, [createVNode(unref(PanelLeftClose), {
							size: 17,
							"aria-hidden": "true"
						})], 8, _hoisted_6$2),
						createBaseVNode("button", {
							id: "logoutBtn",
							class: "icon-button",
							type: "button",
							title: "退出登录",
							"aria-label": "退出登录",
							disabled: unref(auth).status === "submitting",
							onClick: _cache[2] || (_cache[2] = (...args) => unref(auth).logout && unref(auth).logout(...args))
						}, [createVNode(unref(LogOut), {
							size: 17,
							"aria-hidden": "true"
						})], 8, _hoisted_7$2)
					])
				], 64);
			};
		}
	});
	//#endregion
	//#region src/components/AuthView.vue?vue&type=script&setup=true&lang.ts
	var _hoisted_1$1 = { class: "auth-panel" };
	var _hoisted_2$1 = { class: "auth-panel-inner" };
	var _hoisted_3$1 = {
		class: "auth-tabs",
		role: "tablist",
		"aria-label": "账户操作"
	};
	var _hoisted_4$1 = ["aria-selected"];
	var _hoisted_5$1 = ["aria-selected"];
	var _hoisted_6$1 = ["disabled"];
	var _hoisted_7$1 = ["autocomplete", "disabled"];
	var _hoisted_8$1 = {
		id: "authError",
		class: "form-error",
		"aria-live": "polite"
	};
	var _hoisted_9$1 = ["disabled"];
	//#endregion
	//#region src/components/AuthView.vue
	var AuthView_default = /* @__PURE__ */ defineComponent({
		__name: "AuthView",
		setup(__props) {
			const auth = useAuthStore();
			const route = useRoute();
			const router = useRouter();
			const username = /* @__PURE__ */ ref("");
			const password = /* @__PURE__ */ ref("");
			const mode = computed(() => route.name === "register" ? "register" : "login");
			const submitting = computed(() => auth.status === "submitting");
			watch(mode, () => {
				auth.error = "";
			});
			async function selectMode(nextMode) {
				await router.push({ name: nextMode });
			}
			async function submit() {
				await auth.authenticate(mode.value, username.value, password.value);
				if (auth.status === "authenticated") password.value = "";
			}
			return (_ctx, _cache) => {
				return openBlock(), createElementBlock(Fragment, null, [_cache[10] || (_cache[10] = createStaticVNode("<section class=\"auth-scene\"><div class=\"auth-brand\"><div class=\"brand-lockup\"><span class=\"brand-seal\">剧</span><span>AI 悬疑推理</span></div><div class=\"auth-copy\"><p class=\"case-label\">CASE SYSTEM / 01</p><h1>剧镜</h1><p class=\"auth-lead\">每一份证词，都藏着另一面真相。</p></div><div class=\"scene-status\"><span><i></i>DM 已待命</span><span>角色知识隔离</span><span>本地案件档案</span></div></div></section>", 1)), createBaseVNode("section", _hoisted_1$1, [createBaseVNode("div", _hoisted_2$1, [
					_cache[6] || (_cache[6] = createBaseVNode("p", { class: "case-label" }, "INVESTIGATOR ACCESS", -1)),
					_cache[7] || (_cache[7] = createBaseVNode("h2", null, "进入调查室", -1)),
					_cache[8] || (_cache[8] = createBaseVNode("p", { class: "auth-subtitle" }, "登录后继续你的案件，或建立新的调查员档案。", -1)),
					createBaseVNode("div", _hoisted_3$1, [createBaseVNode("button", {
						id: "loginTab",
						class: normalizeClass(["tab-button", { active: mode.value === "login" }]),
						type: "button",
						role: "tab",
						"aria-selected": mode.value === "login",
						onClick: _cache[0] || (_cache[0] = ($event) => selectMode("login"))
					}, "登录", 10, _hoisted_4$1), createBaseVNode("button", {
						id: "registerTab",
						class: normalizeClass(["tab-button", { active: mode.value === "register" }]),
						type: "button",
						role: "tab",
						"aria-selected": mode.value === "register",
						onClick: _cache[1] || (_cache[1] = ($event) => selectMode("register"))
					}, "注册", 10, _hoisted_5$1)]),
					createBaseVNode("form", {
						id: "authForm",
						onSubmit: withModifiers(submit, ["prevent"])
					}, [
						createBaseVNode("label", null, [_cache[4] || (_cache[4] = createBaseVNode("span", null, "调查员代号", -1)), withDirectives(createBaseVNode("input", {
							id: "usernameInput",
							"onUpdate:modelValue": _cache[2] || (_cache[2] = ($event) => username.value = $event),
							autocomplete: "username",
							minlength: "3",
							maxlength: "32",
							placeholder: "输入用户名",
							disabled: submitting.value,
							required: ""
						}, null, 8, _hoisted_6$1), [[vModelText, username.value]])]),
						createBaseVNode("label", null, [_cache[5] || (_cache[5] = createBaseVNode("span", null, "访问密码", -1)), withDirectives(createBaseVNode("input", {
							id: "passwordInput",
							"onUpdate:modelValue": _cache[3] || (_cache[3] = ($event) => password.value = $event),
							type: "password",
							autocomplete: mode.value === "login" ? "current-password" : "new-password",
							minlength: "6",
							placeholder: "至少 6 位",
							disabled: submitting.value,
							required: ""
						}, null, 8, _hoisted_7$1), [[vModelText, password.value]])]),
						createBaseVNode("p", _hoisted_8$1, toDisplayString(unref(auth).error), 1),
						createBaseVNode("button", {
							id: "authSubmit",
							class: "primary-button wide",
							type: "submit",
							disabled: submitting.value
						}, toDisplayString(submitting.value ? "处理中" : mode.value === "login" ? "登录" : "创建账户"), 9, _hoisted_9$1)
					], 32),
					_cache[9] || (_cache[9] = createBaseVNode("p", { class: "local-note" }, [createBaseVNode("span", null, "●"), createTextVNode("账户与案件记录保存在本机")], -1))
				])])], 64);
			};
		}
	});
	//#endregion
	//#region src/queries/game-records.ts
	var gameRecordsQueryKey = (userId) => ["game-records", userId];
	function invalidateGameRecords(queryClient, userId) {
		return queryClient.invalidateQueries({
			queryKey: gameRecordsQueryKey(userId),
			refetchType: "none"
		});
	}
	function useGameRecordsQuery(enabled) {
		const auth = useAuthStore();
		const queryClient = useQueryClient();
		const queryKey = computed(() => gameRecordsQueryKey(auth.user?.id || 0));
		const query = useQuery({
			queryKey,
			queryFn: ({ signal }) => getApiClient().request("/api/games", { signal }),
			enabled: computed(() => enabled.value && Boolean(auth.user))
		});
		const deletion = useMutation({
			mutationKey: ["delete-game-record"],
			mutationFn: async (game) => {
				await getApiClient().request(`/api/games/${game.id}`, { method: "DELETE" });
				return game;
			},
			onMutate: async (game) => {
				const key = queryKey.value;
				await queryClient.cancelQueries({ queryKey: key });
				const previous = queryClient.getQueryData(key);
				queryClient.setQueryData(key, (records = []) => records.filter((record) => record.id !== game.id));
				return {
					key,
					previous
				};
			},
			onError: (_error, _game, context) => {
				if (context?.previous) queryClient.setQueryData(context.key, context.previous);
			},
			onSettled: (_data, _error, _game, context) => {
				queryClient.invalidateQueries({ queryKey: context?.key || queryKey.value });
			}
		});
		return {
			...query,
			deleteRecord: deletion.mutateAsync,
			deletingGameId: computed(() => deletion.isPending.value ? deletion.variables.value?.id ?? null : null),
			invalidate: () => {
				const userId = auth.user?.id;
				return userId ? invalidateGameRecords(queryClient, userId) : Promise.resolve();
			}
		};
	}
	function queryErrorMessage(error) {
		return error instanceof Error ? error.message : "读取案件档案失败";
	}
	//#endregion
	//#region src/components/CaseRecordsView.vue?vue&type=script&setup=true&lang.ts
	var _hoisted_1 = { class: "page-header" };
	var _hoisted_2 = ["disabled"];
	var _hoisted_3 = ["aria-busy"];
	var _hoisted_4 = {
		key: 0,
		class: "empty-state"
	};
	var _hoisted_5 = {
		key: 1,
		class: "empty-state records-error-state"
	};
	var _hoisted_6 = {
		key: 2,
		class: "empty-state"
	};
	var _hoisted_7 = { class: "record-title" };
	var _hoisted_8 = { class: "record-cell" };
	var _hoisted_9 = { class: "record-cell" };
	var _hoisted_10 = { class: "record-cell" };
	var _hoisted_11 = { class: "record-actions" };
	var _hoisted_12 = ["onClick"];
	var _hoisted_13 = ["disabled", "onClick"];
	//#endregion
	//#region src/components/CaseRecordsView.vue
	var CaseRecordsView_default = /* @__PURE__ */ defineComponent({
		__name: "CaseRecordsView",
		setup(__props) {
			const categoryNames = {
				mystery: "悬疑推理",
				adventure: "冒险探索",
				fantasy: "奇幻世界",
				history: "历史演绎",
				custom: "自定义"
			};
			const modeNames = {
				narrative: "剧情体验",
				deduction: "推理对抗",
				faction: "阵营博弈"
			};
			const route = useRoute();
			const auth = useAuthStore();
			const queryClient = useQueryClient();
			const enabled = computed(() => route.name === "case-list");
			const { data, error, isFetching, isPending, refetch, deleteRecord, deletingGameId, invalidate } = useGameRecordsQuery(enabled);
			const games = computed(() => data.value || []);
			const confirmingGameId = /* @__PURE__ */ ref(null);
			let confirmationTimer = null;
			let stopInvalidationListener = null;
			function clearDeleteConfirmation() {
				if (confirmationTimer !== null) window.clearTimeout(confirmationTimer);
				confirmationTimer = null;
				confirmingGameId.value = null;
			}
			function formatUpdatedAt(value) {
				const date = new Date(value);
				return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
			}
			async function refresh() {
				clearDeleteConfirmation();
				const result = await refetch({ cancelRefetch: true });
				if (result.error) appEvents.emit("toast:show", { message: queryErrorMessage(result.error) });
			}
			async function openRecord(game) {
				clearDeleteConfirmation();
				await invalidate();
				appEvents.emit("records:open", { gameId: game.id });
			}
			async function requestDelete(game) {
				if (confirmingGameId.value !== game.id) {
					clearDeleteConfirmation();
					confirmingGameId.value = game.id;
					confirmationTimer = window.setTimeout(clearDeleteConfirmation, 3200);
					return;
				}
				clearDeleteConfirmation();
				try {
					await deleteRecord(game);
					appEvents.emit("records:deleted", {
						gameId: game.id,
						title: game.title
					});
				} catch (deleteError) {
					appEvents.emit("toast:show", { message: queryErrorMessage(deleteError) });
				}
			}
			watch(() => auth.user?.id, (userId, previousUserId) => {
				if (previousUserId && previousUserId !== userId) queryClient.removeQueries({ queryKey: gameRecordsQueryKey(previousUserId) });
			});
			watch(enabled, (active) => {
				if (!active) clearDeleteConfirmation();
			});
			onMounted(() => {
				stopInvalidationListener = appEvents.on("records:invalidate", () => {
					const userId = auth.user?.id;
					if (userId) invalidateGameRecords(queryClient, userId);
				});
			});
			onBeforeUnmount(() => {
				clearDeleteConfirmation();
				stopInvalidationListener?.();
			});
			return (_ctx, _cache) => {
				return openBlock(), createElementBlock(Fragment, null, [
					createBaseVNode("header", _hoisted_1, [_cache[0] || (_cache[0] = createBaseVNode("div", null, [
						createBaseVNode("p", { class: "case-label" }, "CASE ARCHIVE"),
						createBaseVNode("h2", null, "案件档案"),
						createBaseVNode("p", null, "继续调查或查看已经完成的案件。")
					], -1)), createBaseVNode("button", {
						id: "refreshRecordsBtn",
						class: normalizeClass(["icon-button bordered records-refresh", { "is-loading": unref(isFetching) }]),
						type: "button",
						title: "刷新档案",
						"aria-label": "刷新档案",
						disabled: unref(isFetching) || unref(deletingGameId) !== null,
						onClick: refresh
					}, [createVNode(unref(RefreshCw), {
						size: 17,
						"aria-hidden": "true"
					})], 10, _hoisted_2)]),
					_cache[5] || (_cache[5] = createBaseVNode("div", {
						class: "records-header",
						"aria-hidden": "true"
					}, [
						createBaseVNode("span", null, "案件"),
						createBaseVNode("span", null, "类型"),
						createBaseVNode("span", null, "模式"),
						createBaseVNode("span", null, "进度"),
						createBaseVNode("span")
					], -1)),
					createBaseVNode("div", {
						id: "recordsList",
						class: "records-list",
						"aria-busy": unref(isFetching)
					}, [unref(isPending) ? (openBlock(), createElementBlock("div", _hoisted_4, "正在读取记录...")) : unref(error) && !games.value.length ? (openBlock(), createElementBlock("div", _hoisted_5, [createBaseVNode("span", null, toDisplayString(unref(queryErrorMessage)(unref(error))), 1), createBaseVNode("button", {
						class: "secondary-button",
						type: "button",
						onClick: refresh
					}, [createVNode(unref(RefreshCw), {
						size: 15,
						"aria-hidden": "true"
					}), _cache[1] || (_cache[1] = createTextVNode("重新读取 ", -1))])])) : !games.value.length ? (openBlock(), createElementBlock("div", _hoisted_6, "暂无游戏记录")) : createCommentVNode("", true), (openBlock(true), createElementBlock(Fragment, null, renderList(games.value, (game) => {
						return openBlock(), createElementBlock("article", {
							key: game.id,
							class: "record-row"
						}, [
							createBaseVNode("div", _hoisted_7, [createBaseVNode("strong", null, toDisplayString(game.title), 1), createBaseVNode("span", null, toDisplayString(formatUpdatedAt(game.updated_at)), 1)]),
							createBaseVNode("div", _hoisted_8, [_cache[2] || (_cache[2] = createBaseVNode("span", null, "类型", -1)), createTextVNode(toDisplayString(categoryNames[game.category] || game.category), 1)]),
							createBaseVNode("div", _hoisted_9, [_cache[3] || (_cache[3] = createBaseVNode("span", null, "模式", -1)), createTextVNode(toDisplayString(modeNames[game.mode] || game.mode), 1)]),
							createBaseVNode("div", _hoisted_10, [_cache[4] || (_cache[4] = createBaseVNode("span", null, "进度", -1)), createTextVNode(toDisplayString(game.current_stage) + "/" + toDisplayString(game.total_stages), 1)]),
							createBaseVNode("div", _hoisted_11, [createBaseVNode("button", {
								class: "secondary-button",
								type: "button",
								onClick: ($event) => openRecord(game)
							}, [createVNode(unref(FolderOpen), {
								size: 14,
								"aria-hidden": "true"
							}), createTextVNode(toDisplayString(game.status === "completed" ? "查看" : "继续"), 1)], 8, _hoisted_12), createBaseVNode("button", {
								class: normalizeClass(["record-delete-button", { confirming: confirmingGameId.value === game.id }]),
								type: "button",
								disabled: unref(deletingGameId) !== null,
								onClick: ($event) => requestDelete(game)
							}, [createVNode(unref(Trash2), {
								size: 14,
								"aria-hidden": "true"
							}), createBaseVNode("b", null, toDisplayString(unref(deletingGameId) === game.id ? "删除中" : confirmingGameId.value === game.id ? "确认删除" : "删除"), 1)], 10, _hoisted_13)])
						]);
					}), 128))], 8, _hoisted_3)
				], 64);
			};
		}
	});
	//#endregion
	//#region src/App.vue
	var App_default = /* @__PURE__ */ defineComponent({
		__name: "App",
		setup(__props) {
			return (_ctx, _cache) => {
				return openBlock(), createElementBlock(Fragment, null, [
					(openBlock(), createBlock(Teleport, { to: "#authView" }, [createVNode(AuthView_default)])),
					(openBlock(), createBlock(Teleport, { to: "#appSidebar" }, [createVNode(AppSidebar_default)])),
					(openBlock(), createBlock(Teleport, { to: "#recordsView" }, [createVNode(CaseRecordsView_default)]))
				], 64);
			};
		}
	});
	//#endregion
	//#region src/state.ts
	function createAppState() {
		return {
			authMode: "login",
			csrfToken: "",
			user: null,
			catalog: null,
			category: "mystery",
			mode: "deduction",
			script: null,
			builtinScriptId: null,
			preview: null,
			game: null,
			ws: null,
			expectedSocketClosures: /* @__PURE__ */ new WeakSet(),
			reconnectTimer: null,
			reconnectAttempts: 0,
			lastEventId: 0,
			waitingForAgent: false,
			currentPhase: "investigation",
			phaseSummary: null,
			activeMechanics: [],
			enabledActions: [
				"public_speech",
				"search",
				"whisper"
			],
			countdownTimer: null,
			countdownDeadline: null,
			agentActivityNode: null,
			notebook: {
				automatic: [],
				clues: [],
				manualNotes: "",
				activeSection: "automatic",
				saveTimer: null,
				dirty: false
			},
			roleRecords: null,
			stageResolution: null,
			selectedVoteRoleId: null,
			sidebarCollapsed: false,
			compactPanel: "dialogue",
			whisper: {
				enabled: false,
				activeTargetRoleId: null,
				channel: "public"
			}
		};
	}
	//#endregion
	//#region src/command-outbox.ts
	var CommandOutbox = class {
		pending = /* @__PURE__ */ new Map();
		retain(envelope, context) {
			if (this.pending.size >= 32) throw new Error("待确认操作过多，请等待服务端确认");
			this.pending.set(String(envelope.request_id), {
				envelope,
				context: { ...context }
			});
		}
		acknowledge(raw) {
			if (!raw || typeof raw !== "object") return;
			const message = raw;
			if (message.kind === "resume") {
				const events = message.payload?.events;
				if (Array.isArray(events)) events.forEach((event) => this.acknowledge(event));
			}
			if (message.kind !== "event" && message.kind !== "error") return;
			const record = this.pending.get(String(message.request_id));
			if (record && message.game_id === record.context.gameId) this.pending.delete(String(message.request_id));
		}
		reconcile(context) {
			const commands = [];
			let expiredCount = 0;
			for (const [requestId, record] of this.pending) {
				if (record.context.gameId !== context.gameId) continue;
				if (record.context.stage !== context.stage || record.context.phase !== context.phase) {
					this.pending.delete(requestId);
					expiredCount += 1;
				} else commands.push(record.envelope);
			}
			return {
				commands,
				expiredCount
			};
		}
		clear() {
			this.pending.clear();
		}
	};
	function isRecord(value) {
		return Boolean(value) && typeof value === "object" && !Array.isArray(value);
	}
	function eventIdOf(message) {
		const value = Number(message.event_id || 0);
		return Number.isSafeInteger(value) && value > 0 ? value : 0;
	}
	function createRequestId() {
		if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
		return `${Date.now()}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
	}
	function buildCommandEnvelope(gameId, command, requestId = createRequestId()) {
		const { type, ...payload } = command;
		if (!Number.isSafeInteger(gameId) || gameId <= 0) throw new Error("game_id 必须是正整数");
		if (typeof type !== "string" || !type) throw new Error("实时命令缺少 type");
		return {
			protocol_version: "1.0",
			kind: "command",
			type,
			request_id: requestId,
			game_id: gameId,
			payload
		};
	}
	function reduceRealtimeEnvelope(rawMessage, currentEventId) {
		if (!isRecord(rawMessage)) throw new Error("实时消息必须是对象");
		if (rawMessage.protocol_version !== "1.0") return {
			lastEventId: currentEventId,
			snapshotGame: null,
			messages: [rawMessage]
		};
		const kind = rawMessage.kind;
		const nextEventId = Math.max(currentEventId, eventIdOf(rawMessage));
		if (kind === "snapshot") {
			if (!isRecord(rawMessage.payload) || !isRecord(rawMessage.payload.game)) throw new Error("实时快照缺少 game");
			const phaseMessages = rawMessage.payload.phase_messages;
			if (!Array.isArray(phaseMessages) || !phaseMessages.every(isRecord)) throw new Error("实时快照 phase_messages 无效");
			return {
				lastEventId: nextEventId,
				snapshotGame: rawMessage.payload.game,
				messages: phaseMessages
			};
		}
		if (kind === "resume") {
			if (!isRecord(rawMessage.payload) || !Array.isArray(rawMessage.payload.events)) throw new Error("实时续传 events 无效");
			let cursor = currentEventId;
			const messages = [];
			for (const event of rawMessage.payload.events) {
				const reduction = reduceRealtimeEnvelope(event, cursor);
				cursor = reduction.lastEventId;
				messages.push(...reduction.messages);
			}
			return {
				lastEventId: Math.max(cursor, nextEventId),
				snapshotGame: null,
				messages
			};
		}
		if (kind !== "event" && kind !== "error") throw new Error("不支持的实时消息类型");
		const eventId = eventIdOf(rawMessage);
		if (eventId && eventId <= currentEventId) return {
			lastEventId: currentEventId,
			snapshotGame: null,
			messages: []
		};
		if (!isRecord(rawMessage.payload)) throw new Error("实时事件 payload 无效");
		const payloadType = typeof rawMessage.payload.type === "string" ? rawMessage.payload.type : rawMessage.type;
		if (typeof payloadType !== "string" || !payloadType) throw new Error("实时事件缺少 type");
		return {
			lastEventId: nextEventId,
			snapshotGame: null,
			messages: [{
				...rawMessage.payload,
				type: payloadType
			}]
		};
	}
	//#endregion
	//#region src/legacy-app.js
	function mountLegacyApp() {
		const state = createAppState();
		const commandOutbox = new CommandOutbox();
		const appRouter = getNavigation();
		const authStore = useAuthStore();
		const uiStore = useUiStore();
		const authChannel = "BroadcastChannel" in window ? new BroadcastChannel("ai-mm-auth") : null;
		const els = Object.fromEntries([
			"authView",
			"appView",
			"appSidebar",
			"createView",
			"recordsView",
			"gameView",
			"categoryGrid",
			"modeControl",
			"selectedCategoryText",
			"selectedModeText",
			"uploadZone",
			"scriptFileInput",
			"chooseFileBtn",
			"exampleScriptBtn",
			"uploadTitle",
			"uploadMeta",
			"scriptError",
			"scriptPreview",
			"previewTitle",
			"previewStages",
			"previewRoles",
			"previewAgents",
			"roleOptions",
			"startGameBtn",
			"leaveGameBtn",
			"expandSidebarBtn",
			"gameModeLabel",
			"gameTitle",
			"currentStage",
			"totalStages",
			"playerIntel",
			"searchTargets",
			"messages",
			"speechForm",
			"speechInput",
			"humanRole",
			"totalRoles",
			"agentCount",
			"castList",
			"dispatchList",
			"advanceBtn",
			"toast",
			"whisperSection",
			"whisperTarget",
			"whisperInviteBtn",
			"whisperCloseBtn",
			"whisperStatus",
			"channelControl",
			"publicChannelBtn",
			"privateChannelBtn",
			"channelTarget",
			"speechSubmitBtn",
			"compactGameTabs",
			"compactIntelTab",
			"compactDialogueTab",
			"compactDmTab",
			"gameLayout",
			"intelPanel",
			"dialoguePanel",
			"dmPanel",
			"phaseStatus",
			"roundClock",
			"roundCountdown",
			"phaseStage",
			"phaseRoundLabel",
			"phaseRoundTitle",
			"phaseEyebrow",
			"phaseTitle",
			"narrationBlock",
			"dmNarration",
			"streamCursor",
			"privateDossier",
			"dossierRole",
			"dossierIdentity",
			"dossierBlocks",
			"dossierTask",
			"phaseHint",
			"phaseContinueBtn",
			"phaseObjectiveList",
			"phaseCastList",
			"stageResolutionPanel",
			"resolutionTitle",
			"resolutionMetric",
			"resolutionRoleResults",
			"resolutionVoteSection",
			"resolutionVoteLabel",
			"resolutionVotePrompt",
			"resolutionVoteRule",
			"resolutionCandidates",
			"submitStageVoteBtn",
			"resolutionVoteResult",
			"phaseRules",
			"investigationEndVoteStatus",
			"agentAutonomyState",
			"notebookAutoTab",
			"notebookCluesTab",
			"notebookManualTab",
			"notebookAutoPane",
			"notebookCluesPane",
			"notebookManualPane",
			"notebookAutoEntries",
			"ownedClues",
			"notebookManualNotes",
			"notebookSaveState",
			"roleRecordsModal",
			"closeRoleRecordsBtn",
			"auditRoleTabs",
			"auditClues",
			"auditAutomaticEntries",
			"auditReasoningEntries",
			"auditStageResults",
			"auditOperations",
			"auditAgentContexts",
			"conversationParticipants"
		].map((id) => [id, document.getElementById(id)]));
		const avatarActionTimers = /* @__PURE__ */ new WeakMap();
		const categoryNames = {
			mystery: "悬疑推理",
			adventure: "冒险探索",
			fantasy: "奇幻世界",
			history: "历史演绎",
			custom: "自定义"
		};
		const modeNames = {
			narrative: "剧情体验",
			deduction: "推理对抗",
			faction: "阵营博弈"
		};
		const apiClient = getApiClient();
		async function api(path, options = {}) {
			try {
				return await apiClient.request(path, options);
			} catch (error) {
				if (error instanceof ApiError && error.status === 404 && error.body.detail === "Not Found" && (path.includes("/notebook") || path.includes("/role-records"))) throw new Error("后端仍在运行旧版本，请重启项目后刷新页面");
				throw error;
			}
		}
		function showAuth(preserveReturnPath = true) {
			if (preserveReturnPath) appRouter.rememberCurrentReturnPath();
			else appRouter.clearReturnPath();
			authStore.clearSession();
			uiStore.setGameActive(false);
			state.csrfToken = "";
			state.user = null;
			state.script = null;
			state.builtinScriptId = null;
			state.preview = null;
			state.game = null;
			state.lastEventId = 0;
			state.roleRecords = null;
			setSidebarCollapsed(false);
			els.appView.classList.remove("game-active");
			syncAccountAvatar();
			resetNotebook();
			closeRoleRecords();
			localStorage.removeItem("ai_mm_token");
			closeGameSocket();
			stopCountdown();
			els.uploadTitle.textContent = "拖入案件文件，或从本机选择";
			els.uploadMeta.textContent = "JSON · 最大 5 MB";
			els.scriptPreview.classList.add("hidden");
			els.scriptError.textContent = "";
			setCreationStep(1);
			els.authView.classList.remove("hidden");
			els.appView.classList.add("hidden");
			const authMode = appRouter.current().name === "register" ? "register" : "login";
			appRouter.replace({ name: authMode });
			animateView(els.authView);
		}
		async function enterApp(user) {
			authStore.setSession(user);
			state.csrfToken = authStore.csrfToken;
			state.user = authStore.user;
			els.authView.classList.add("hidden");
			els.appView.classList.remove("hidden");
			state.catalog = await api("/api/catalog");
			renderCatalog();
			const returnPath = appRouter.consumeReturnPath();
			if (returnPath) await appRouter.replacePath(returnPath);
			else if ([
				"login",
				"register",
				"not-found"
			].includes(appRouter.current().name)) await appRouter.replace({ name: "case-create" });
			await restoreRoute();
		}
		function syncAccountAvatar() {
			uiStore.setGameActive(Boolean(state.user) && els.appView.classList.contains("game-active"));
		}
		function renderCatalog() {
			const category = state.catalog.categories.find((item) => item.id === "mystery");
			const mode = state.catalog.modes.find((item) => item.id === "deduction");
			state.category = category?.id || "mystery";
			state.mode = mode?.id || "deduction";
			els.selectedCategoryText.textContent = category?.name || "悬疑推理";
			els.selectedModeText.textContent = mode?.name || "推理对抗";
			els.categoryGrid.innerHTML = "";
			els.modeControl.innerHTML = "";
		}
		function showPage(name, updateHistory = true) {
			closeGameSocket();
			closeRoleRecords();
			setSidebarCollapsed(false);
			els.appView.classList.remove("game-active");
			syncAccountAvatar();
			for (const view of [
				els.createView,
				els.recordsView,
				els.gameView
			]) view.classList.add("hidden");
			if (name === "records") {
				if (updateHistory) appRouter.push({ name: "case-list" });
				els.recordsView.classList.remove("hidden");
				animateView(els.recordsView);
			} else {
				if (updateHistory) appRouter.push({ name: "case-create" });
				els.createView.classList.remove("hidden");
				setCreationStep(state.preview ? 2 : 1);
				animateView(els.createView);
			}
		}
		async function restoreRoute() {
			const route = appRouter.current();
			if (route.name === "case-detail") {
				await openGame(route.gameId, null, false);
				return;
			}
			if (route.name === "case-list") {
				showPage("records", false);
				return;
			}
			if (route.name !== "case-create") await appRouter.replace({ name: "case-create" });
			showPage("create", false);
		}
		function setCreationStep(step) {
			document.querySelectorAll(".step-indicator span").forEach((item, index) => {
				const current = index + 1;
				item.classList.toggle("active", current === step);
				item.classList.toggle("complete", current < step);
			});
		}
		async function readScriptFile(file) {
			els.scriptError.textContent = "";
			if (!file) return;
			if (file.size > 5242880) {
				els.scriptError.textContent = "剧本文件不能超过 5 MB";
				return;
			}
			try {
				state.builtinScriptId = null;
				state.script = JSON.parse(await file.text());
				els.uploadTitle.textContent = file.name;
				els.uploadMeta.textContent = `${Math.max(1, Math.ceil(file.size / 1024))} KB · JSON`;
				await inspectScript();
			} catch (error) {
				state.script = null;
				els.scriptPreview.classList.add("hidden");
				setCreationStep(1);
				els.scriptError.textContent = error instanceof SyntaxError ? "JSON 格式无效" : error.message;
			}
		}
		async function inspectScript() {
			if (!state.script && !state.builtinScriptId) return;
			try {
				state.preview = await api("/api/scripts/inspect", {
					method: "POST",
					body: JSON.stringify({
						mode: state.mode,
						...scriptSource()
					})
				});
				els.scriptError.textContent = "";
				renderScriptPreview();
			} catch (error) {
				state.preview = null;
				els.scriptPreview.classList.add("hidden");
				setCreationStep(1);
				els.scriptError.textContent = error.message;
			}
		}
		function scriptSource() {
			return state.builtinScriptId ? { script_id: state.builtinScriptId } : { script: state.script };
		}
		function renderScriptPreview() {
			const preview = state.preview;
			els.previewTitle.textContent = preview.title;
			els.previewStages.textContent = String(preview.total_stages);
			els.previewRoles.textContent = String(preview.role_count);
			els.previewAgents.textContent = String(preview.ai_agent_count);
			els.roleOptions.innerHTML = "";
			preview.playable_roles.forEach((role, index) => {
				const label = document.createElement("label");
				label.className = "role-option";
				label.innerHTML = `
      <input type="radio" name="player-role" value="${escapeHtml(role.role_id)}" ${index === 0 ? "checked" : ""} />
      <span><strong>${escapeHtml(role.role_name)}</strong><span>${escapeHtml(role.public_identity)}</span></span>`;
				els.roleOptions.appendChild(label);
			});
			els.scriptPreview.classList.remove("hidden");
			setCreationStep(2);
		}
		async function startGame() {
			const selectedRole = document.querySelector("input[name=\"player-role\"]:checked");
			if (!state.script && !state.builtinScriptId || !state.preview || !selectedRole) return;
			setCreationStep(3);
			els.startGameBtn.disabled = true;
			els.startGameBtn.innerHTML = "<span>DM 正在建立调查现场...</span><b>···</b>";
			try {
				const game = await api("/api/games", {
					method: "POST",
					body: JSON.stringify({
						category: state.category,
						mode: state.mode,
						player_role_id: selectedRole.value,
						...scriptSource()
					})
				});
				appEvents.emit("records:invalidate", {});
				await openGame(game.id, game);
			} catch (error) {
				setCreationStep(2);
				toast(error.message);
			} finally {
				els.startGameBtn.disabled = false;
				els.startGameBtn.innerHTML = "<span>启动 DM，进入案发现场</span><b>→</b>";
			}
		}
		async function openGame(gameId, summary = null, updateHistory = true) {
			closeGameSocket();
			state.lastEventId = 0;
			let detail;
			try {
				detail = await api(`/api/games/${gameId}`);
			} catch (error) {
				toast(error.message);
				return;
			}
			state.game = {
				...summary || {},
				...detail
			};
			if (updateHistory) appRouter.push({
				name: "case-detail",
				gameId: Number(gameId)
			});
			state.roleRecords = null;
			setSidebarCollapsed(false);
			els.appView.classList.add("game-active");
			syncAccountAvatar();
			closeRoleRecords();
			els.createView.classList.add("hidden");
			els.recordsView.classList.add("hidden");
			els.gameView.classList.remove("hidden");
			animateView(els.gameView);
			els.gameTitle.textContent = detail.title;
			els.gameModeLabel.textContent = `${categoryNames[detail.category] || detail.category} · ${modeNames[detail.mode] || detail.mode}`;
			els.currentStage.textContent = String(detail.current_stage);
			els.totalStages.textContent = String(detail.total_stages);
			els.messages.innerHTML = "";
			resetWhisper();
			resetPhaseExperience();
			resetNotebook();
			setCompactGamePanel("dialogue", false);
			loadNotebook(gameId);
			connectGame(gameId);
		}
		function setSidebarCollapsed(collapsed, focusTarget = false) {
			const active = Boolean(collapsed);
			state.sidebarCollapsed = active;
			uiStore.setSidebarCollapsed(active);
			els.appView?.classList.toggle("sidebar-collapsed", active);
			els.appSidebar?.setAttribute("aria-hidden", String(active));
			els.appSidebar?.toggleAttribute("inert", active);
			els.expandSidebarBtn?.setAttribute("aria-expanded", String(!active));
			if (focusTarget) window.requestAnimationFrame(() => {
				(active ? els.expandSidebarBtn : document.getElementById("collapseSidebarBtn"))?.focus();
			});
		}
		const compactGameMedia = window.matchMedia("(max-width: 1180px)");
		function syncCompactGamePanel() {
			const compact = compactGameMedia.matches;
			const panels = {
				intel: els.intelPanel,
				dialogue: els.dialoguePanel,
				dm: els.dmPanel
			};
			Object.entries(panels).forEach(([name, panel]) => {
				if (compact) panel.setAttribute("aria-hidden", String(name !== state.compactPanel));
				else panel.removeAttribute("aria-hidden");
			});
		}
		function setCompactGamePanel(panelName, animate = true) {
			if (![
				"intel",
				"dialogue",
				"dm"
			].includes(panelName)) return;
			state.compactPanel = panelName;
			els.gameLayout.dataset.compactPanel = panelName;
			document.querySelectorAll(".compact-game-tab").forEach((button) => {
				const selected = button.dataset.panel === panelName;
				button.classList.toggle("active", selected);
				button.setAttribute("aria-selected", String(selected));
				button.tabIndex = selected ? 0 : -1;
			});
			syncCompactGamePanel();
			const panel = {
				intel: els.intelPanel,
				dialogue: els.dialoguePanel,
				dm: els.dmPanel
			}[panelName];
			if (compactGameMedia.matches && animate) animateView(panel);
			if (panelName === "dialogue") els.messages.scrollTop = els.messages.scrollHeight;
		}
		const scenePhaseOrder = [
			"briefing",
			"private_reveal",
			"investigation",
			"dm_hosting"
		];
		function resetPhaseExperience() {
			stopCountdown();
			clearAgentActivity();
			state.currentPhase = "briefing";
			state.phaseSummary = null;
			state.activeMechanics = [];
			state.enabledActions = [];
			state.stageResolution = null;
			state.selectedVoteRoleId = null;
			els.phaseStage.classList.add("hidden");
			els.privateDossier.classList.add("hidden");
			els.stageResolutionPanel.classList.add("hidden");
			els.investigationEndVoteStatus.classList.add("hidden");
			els.investigationEndVoteStatus.innerHTML = "";
			els.streamCursor.classList.add("hidden");
			els.dmNarration.textContent = "";
			els.phaseContinueBtn.disabled = true;
			els.roundClock.classList.add("hidden");
		}
		function renderScenePhase(summary) {
			if (!summary) return;
			state.phaseSummary = summary;
			state.currentPhase = summary.phase;
			state.enabledActions = summary.enabled_actions || [];
			renderOwnedClues();
			els.currentStage.textContent = String(summary.stage);
			els.totalStages.textContent = String(summary.total_stages);
			els.phaseStatus.textContent = summary.phase_label;
			els.phaseRoundLabel.textContent = `ACT ${String(summary.stage).padStart(2, "0")}`;
			els.phaseRoundTitle.textContent = summary.stage_title;
			els.phaseTitle.textContent = summary.stage_title;
			renderInvestigationRules(summary, (summary.player_penalties || []).map((penalty) => `${penalty.label}：${penalty.description}`).join("；"));
			els.agentAutonomyState.classList.toggle("hidden", !summary.autonomy?.enabled);
			const currentIndex = scenePhaseOrder.indexOf(summary.phase);
			document.querySelectorAll(".phase-sequence li").forEach((item, index) => {
				item.classList.toggle("active", index === currentIndex);
				item.classList.toggle("complete", index < currentIndex);
			});
			renderPhaseObjectives(summary.public_tasks || []);
			if (summary.resolution) renderStageResolution(summary.resolution);
			if (summary.phase === "investigation") {
				els.advanceBtn.disabled = !summary.can_manual_end;
				els.advanceBtn.textContent = summary.can_manual_end ? summary.end_condition?.met ? "建议目标已达成，发起结束投票" : "发起结束投票" : "等待条件达成或计时结束";
				applyActionAvailability();
				return;
			}
			stopCountdown();
			showPhaseStage(true);
			els.privateDossier.classList.add("hidden");
			els.phaseEyebrow.textContent = {
				briefing: "DM BRIEFING · 公开信息",
				private_reveal: "ROLE DOSSIER · 仅你可见",
				dm_hosting: "DM HOSTING · 本幕收束"
			}[summary.phase] || "DM HOSTING";
			els.phaseHint.textContent = {
				briefing: "请听完 DM 的案情通报与本幕公开任务",
				private_reveal: "阅读你的独属剧本和个人任务",
				dm_hosting: "DM 正在封存证词并推进故事"
			}[summary.phase] || "";
		}
		function renderInvestigationRules(summary, penaltyText = "") {
			const condition = summary?.end_condition;
			const progress = (condition?.items || []).map((item) => `${item.label} ${item.current}/${item.target}`).join(condition?.mode === "any" ? "，任一达成" : "，");
			const readyText = condition?.met && !condition?.auto_end ? "建议目标已达成但不会自动结束；你可以继续调查或发起结束投票" : "";
			els.phaseRules.textContent = [
				summary?.end_condition_text || "由 DM 根据本幕规则收束",
				progress ? `当前进度：${progress}` : "",
				readyText,
				penaltyText
			].filter(Boolean).join(" · ");
			els.phaseRules.classList.toggle("ready", Boolean(condition?.met));
		}
		function renderInvestigationEndVote(vote) {
			if (!vote) return;
			const ballots = (vote.ballots || []).map((ballot) => `
      <li class="${ballot.approved ? "approved" : "rejected"}">
        <span>${escapeHtml(ballot.voter_role_name)}</span>
        <b>${ballot.approved ? "同意" : "反对"}</b>
      </li>`).join("");
			els.investigationEndVoteStatus.className = `end-vote-status ${vote.approved ? "approved" : "rejected"}`;
			els.investigationEndVoteStatus.innerHTML = `
    <strong>${vote.approved ? "结束投票通过" : "结束投票未通过"}</strong>
    <p>${escapeHtml(vote.message || "")}</p>
    <div><b>${escapeHtml(vote.approved_votes)}/${escapeHtml(vote.total_votes)}</b><span>同意 · 需要 ${escapeHtml(vote.required_votes)} 票</span></div>
    <ul>${ballots}</ul>`;
		}
		function showPhaseStage(show) {
			els.phaseStage.classList.toggle("hidden", !show);
			els.gameLayout.classList.toggle("hidden", show);
			els.compactGameTabs.classList.toggle("hidden", show);
		}
		function renderPhaseObjectives(tasks) {
			els.phaseObjectiveList.innerHTML = "";
			tasks.forEach((task, index) => {
				const item = document.createElement("li");
				item.innerHTML = `<b>${String(index + 1).padStart(2, "0")}</b><span>${escapeHtml(task)}</span>`;
				els.phaseObjectiveList.appendChild(item);
			});
			if (!tasks.length) els.phaseObjectiveList.innerHTML = "<li><span>等待 DM 发布本幕任务</span></li>";
		}
		function renderPhaseCast(roles, humanRoleId) {
			els.phaseCastList.innerHTML = "";
			roles.forEach((role) => {
				const item = document.createElement("div");
				const isHuman = role.role_id === humanRoleId;
				item.className = "phase-cast-item";
				item.innerHTML = `
      ${roleAvatarMarkup(role.role_id, role.role_name, {
					isHuman,
					size: "small",
					live: true
				})}
      <div><strong>${escapeHtml(role.role_name)}</strong><small>${escapeHtml(role.public_identity)}</small></div>`;
				els.phaseCastList.appendChild(item);
			});
		}
		function beginNarration(message) {
			showPhaseStage(true);
			setComposerBusy(false);
			els.privateDossier.classList.add("hidden");
			if (message.phase !== "dm_hosting") els.stageResolutionPanel.classList.add("hidden");
			els.phaseTitle.textContent = message.title || state.phaseSummary?.stage_title || "DM 主持";
			els.dmNarration.textContent = "";
			els.narrationBlock.classList.remove("hidden");
			els.streamCursor.classList.remove("hidden");
			setPhaseContinue("DM 正在讲述", false);
		}
		function appendNarration(content) {
			els.dmNarration.textContent += content || "";
		}
		function finishNarration(message) {
			els.streamCursor.classList.add("hidden");
			setPhaseContinue(message.continue_label || "继续", message.can_continue !== false);
			els.phaseHint.textContent = state.currentPhase === "briefing" ? "公开信息已发布，下一步将向每个角色单独发放剧本" : message.can_continue === false ? "请先完成本幕集体决策，DM 才会开放后续剧情" : "本幕主持已结束，可以继续推进故事";
		}
		function renderPrivateAssignment(message) {
			const assignment = message.assignment;
			renderScenePhase(message.phase);
			showPhaseStage(true);
			els.narrationBlock.classList.add("hidden");
			els.privateDossier.classList.remove("hidden");
			els.stageResolutionPanel.classList.add("hidden");
			els.phaseTitle.textContent = "你的角色剧本";
			els.dossierRole.textContent = assignment.role_name;
			els.dossierIdentity.textContent = assignment.public_identity;
			els.dossierTask.textContent = assignment.personal_task;
			els.dossierBlocks.innerHTML = "";
			assignment.blocks.forEach((block, index) => {
				const item = document.createElement("article");
				item.innerHTML = `
      <span>PRIVATE ${String(index + 1).padStart(2, "0")}</span>
      <p>${escapeHtml(block.content)}</p>`;
				els.dossierBlocks.appendChild(item);
			});
			if (!assignment.blocks.length) els.dossierBlocks.innerHTML = "<article><p>本幕没有新增私人剧本。</p></article>";
			renderIntel(assignment.blocks);
			renderDispatch(message.dispatch);
			setPhaseContinue("我已阅读，进入调查", true);
			els.phaseHint.textContent = "确认后将开放本幕配置的公聊、搜证与私聊操作";
		}
		function openInvestigation(message) {
			renderScenePhase(message.phase);
			els.investigationEndVoteStatus.classList.add("hidden");
			els.investigationEndVoteStatus.innerHTML = "";
			state.activeMechanics = message.active_mechanics || [];
			state.enabledActions = message.phase.enabled_actions || [];
			if (Array.isArray(message.clues)) {
				state.notebook.clues = message.clues;
				renderOwnedClues();
			}
			showPhaseStage(false);
			els.stageResolutionPanel.classList.add("hidden");
			renderIntel((message.stage_info || []).filter((block) => block.visibility !== "public"));
			renderSearchTargets(state.activeMechanics);
			renderWhisperControls(state.activeMechanics, state.game.publicRoles || [], state.game.player_role_id, message.whisper_status);
			applyActionAvailability();
			setCompactGamePanel("dialogue", false);
			addMessage("dm", "DM Agent", `${message.phase.stage_title}调查开始。可用操作：${formatEnabledActions(state.enabledActions)}。${message.phase.autonomy?.enabled ? "角色 Agent 已开始依据各自任务自主调查。" : ""}`);
			startCountdown(message.phase.remaining_seconds);
		}
		function showReplay(message) {
			stopCountdown();
			clearAgentActivity();
			state.currentPhase = "replay";
			state.enabledActions = [];
			if (state.game) state.game.status = "completed";
			showPhaseStage(true);
			els.phaseStatus.textContent = "终局复盘";
			els.phaseRoundLabel.textContent = "CASE CLOSED";
			els.phaseRoundTitle.textContent = "案件终局";
			const finalDecision = message.final_decision;
			const truthRevealed = message.truth_revealed !== false;
			els.phaseEyebrow.textContent = truthRevealed ? "DM REPLAY · 真相公开" : "DM VERDICT · 错误指认";
			els.phaseTitle.textContent = truthRevealed ? "完整案件复盘" : "最终指认失败";
			els.privateDossier.classList.add("hidden");
			els.stageResolutionPanel.classList.add("hidden");
			els.narrationBlock.classList.remove("hidden");
			els.streamCursor.classList.add("hidden");
			const timeline = Object.values(message.timeline || {});
			const narrativeParts = [
				message.verdict,
				message.full_story !== message.verdict ? message.full_story : "",
				...timeline
			].filter(Boolean);
			els.dmNarration.textContent = narrativeParts.join("\n\n");
			const decisionSummary = finalDecision?.selected_role_name ? `最终指认：${finalDecision.selected_role_name}` : "案件已形成最终结果";
			renderPhaseObjectives(truthRevealed ? [
				decisionSummary,
				"指认成立，完整真相已经公开",
				...timeline
			] : [
				decisionSummary,
				"指认未成立，该角色并非真正凶手",
				"真正作案者没有在本局中公开"
			]);
			document.querySelectorAll(".phase-sequence li").forEach((item) => {
				item.classList.remove("active");
				item.classList.add("complete");
			});
			els.phaseHint.textContent = truthRevealed ? "指认正确，本局记录与完整真相已保存" : "指认错误，本局仍已形成明确结局并保存全部记录";
			setPhaseContinue("查看全部角色记录", true);
			els.advanceBtn.classList.add("hidden");
			setComposerBusy(false);
			loadNotebook(state.game?.id);
		}
		function renderStageResolution(resolution) {
			if (!resolution) return;
			if (state.stageResolution?.stage !== resolution.stage || !resolution.vote?.pending) state.selectedVoteRoleId = null;
			state.stageResolution = resolution;
			els.stageResolutionPanel.classList.remove("hidden");
			els.resolutionTitle.textContent = resolution.title || "本幕结算";
			const metric = resolution.metric || {
				label: "阶段成果",
				unit: ""
			};
			els.resolutionMetric.textContent = `${metric.label} · 累计值`;
			els.resolutionRoleResults.innerHTML = "";
			(resolution.role_results || []).forEach((result) => {
				const row = document.createElement("article");
				const sign = Number(result.delta) >= 0 ? "+" : "";
				const reasons = (result.reasons || []).map((reason) => `${reason.label} ${reason.count} 次 ${Number(reason.points) >= 0 ? "+" : ""}${reason.points}${metric.unit}`).join(" · ") || "本幕没有产生可计分操作";
				row.className = "resolution-role-result";
				row.innerHTML = `
      ${roleAvatarMarkup(result.role_id, result.role_name, {
					isHuman: result.controller === "human",
					size: "small",
					live: true
				})}
      <div>
        <strong>${escapeHtml(result.role_name)}</strong>
        <p>${escapeHtml(reasons)}</p>
      </div>
      <span class="${Number(result.delta) < 0 ? "negative" : ""}">${sign}${escapeHtml(result.delta)} ${escapeHtml(metric.unit)}</span>
      <b>${escapeHtml(result.total)} ${escapeHtml(metric.unit)}</b>
      ${taskResultMarkup(result.task_results)}`;
				els.resolutionRoleResults.appendChild(row);
			});
			const vote = resolution.vote;
			els.resolutionVoteSection.classList.toggle("hidden", !vote);
			if (!vote) {
				setPhaseContinue(Number(resolution.stage) >= Number(state.phaseSummary?.total_stages) ? "查看终局复盘" : "进入下一幕", true);
				return;
			}
			els.resolutionVoteLabel.textContent = vote.kind === "final" ? "FINAL ACCUSATION" : "COLLECTIVE DECISION";
			els.resolutionVotePrompt.textContent = vote.prompt;
			els.resolutionVoteRule.textContent = vote.tie_breaker_label || "";
			els.resolutionCandidates.innerHTML = "";
			(vote.eligible_roles || []).forEach((role) => {
				const button = document.createElement("button");
				const selected = state.selectedVoteRoleId === role.role_id;
				const resultSelected = !vote.pending && vote.selected_role_id === role.role_id;
				button.type = "button";
				button.className = [
					"resolution-candidate",
					selected ? "selected" : "",
					resultSelected ? "result-selected" : ""
				].filter(Boolean).join(" ");
				button.dataset.voteRoleId = role.role_id;
				button.setAttribute("role", "radio");
				button.setAttribute("aria-checked", String(selected || resultSelected));
				button.disabled = !vote.pending;
				button.innerHTML = `
      ${roleAvatarMarkup(role.role_id, role.role_name, { size: "small" })}
      <span><strong>${escapeHtml(role.role_name)}</strong><small>${escapeHtml(role.public_identity)}</small></span>`;
				button.addEventListener("click", () => selectResolutionCandidate(role.role_id));
				els.resolutionCandidates.appendChild(button);
			});
			els.submitStageVoteBtn.classList.toggle("hidden", !vote.pending);
			els.submitStageVoteBtn.disabled = !state.selectedVoteRoleId || !vote.pending;
			els.submitStageVoteBtn.innerHTML = `<span>${vote.kind === "final" ? "确认最终指认" : "提交本幕投票"}</span><b>→</b>`;
			els.resolutionVoteResult.classList.toggle("hidden", vote.pending);
			if (vote.pending) {
				els.resolutionVoteResult.innerHTML = "";
				setPhaseContinue(vote.kind === "final" ? "完成最终指认后查看结局" : "完成本幕投票后继续", false);
				return;
			}
			const tally = (vote.tally || []).map((item) => `<li><span>${escapeHtml(item.role_name)}</span><b>${escapeHtml(item.votes)} 票</b></li>`).join("");
			els.resolutionVoteResult.innerHTML = `
    <strong>${vote.correct === true ? "指认成立" : vote.correct === false ? "指认未成立" : "投票完成"}</strong>
    <p>${escapeHtml(vote.outcome_text || "")}</p>
    <ul>${tally}</ul>`;
			setPhaseContinue(vote.kind === "final" ? "查看最终结局" : "进入下一幕", true);
			els.phaseHint.textContent = vote.kind === "final" ? "最终指认已经封存，DM 将发布对应结局" : "本幕投票与处罚已经生效，可以继续推进";
			loadNotebook(state.game?.id);
		}
		function selectResolutionCandidate(roleId) {
			if (!(state.stageResolution?.vote)?.pending) return;
			state.selectedVoteRoleId = roleId;
			document.querySelectorAll(".resolution-candidate").forEach((button) => {
				const selected = button.dataset.voteRoleId === roleId;
				button.classList.toggle("selected", selected);
				button.setAttribute("aria-checked", String(selected));
			});
			els.submitStageVoteBtn.disabled = false;
		}
		function applyActionAvailability() {
			const speechEnabled = state.currentPhase === "investigation" && (state.whisper.channel === "private" ? state.enabledActions.includes("whisper") && Boolean(state.whisper.activeTargetRoleId) : state.enabledActions.includes("public_speech"));
			els.speechForm.classList.toggle("action-locked", !speechEnabled);
			setComposerBusy(false);
			els.advanceBtn.classList.toggle("hidden", state.currentPhase !== "investigation");
		}
		function setPhaseContinue(label, enabled) {
			els.phaseContinueBtn.disabled = !enabled;
			els.phaseContinueBtn.innerHTML = `<span>${escapeHtml(label)}</span><b>→</b>`;
		}
		function formatEnabledActions(actions) {
			const labels = {
				public_speech: "公开询问",
				search: "现场搜证",
				whisper: "秘密询问"
			};
			return actions.map((action) => labels[action] || action).join("、") || "等待 DM 指令";
		}
		function startCountdown(seconds) {
			stopCountdown();
			const duration = Number(seconds);
			if (!Number.isFinite(duration) || duration <= 0) {
				els.roundClock.classList.add("hidden");
				return;
			}
			state.countdownDeadline = Date.now() + duration * 1e3;
			els.roundClock.classList.remove("hidden");
			const tick = () => {
				const remaining = Math.max(0, Math.ceil((state.countdownDeadline - Date.now()) / 1e3));
				const minutes = String(Math.floor(remaining / 60)).padStart(2, "0");
				const secondsPart = String(remaining % 60).padStart(2, "0");
				els.roundCountdown.textContent = `${minutes}:${secondsPart}`;
				els.roundClock.classList.toggle("urgent", remaining <= 60);
				if (remaining <= 0) stopCountdown(false);
			};
			tick();
			state.countdownTimer = window.setInterval(tick, 1e3);
		}
		function stopCountdown(hide = true) {
			if (state.countdownTimer) window.clearInterval(state.countdownTimer);
			state.countdownTimer = null;
			state.countdownDeadline = null;
			if (hide) els.roundClock.classList.add("hidden");
			els.roundClock.classList.remove("urgent");
		}
		async function connectGame(gameId, reconnecting = false) {
			if (state.reconnectTimer) window.clearTimeout(state.reconnectTimer);
			state.reconnectTimer = null;
			let ticket;
			try {
				ticket = (await api(`/api/games/${gameId}/ws-ticket`, { method: "POST" })).ticket;
			} catch (error) {
				if (state.user) {
					toast(error.message || "调查连接凭证获取失败");
					scheduleGameReconnect(gameId);
				}
				return;
			}
			if (!state.game || Number(state.game.id) !== Number(gameId)) return;
			const protocol = location.protocol === "https:" ? "wss" : "ws";
			const socket = new WebSocket(`${protocol}://${location.host}/ws/v1/games/${gameId}?ticket=${encodeURIComponent(ticket)}&after_event_id=${state.lastEventId}`);
			state.ws = socket;
			socket.addEventListener("open", () => {
				state.reconnectAttempts = 0;
				if (reconnecting) toast("调查连接已恢复");
			});
			socket.addEventListener("message", (event) => {
				if (state.ws !== socket) return;
				try {
					handleSocketMessage(JSON.parse(event.data));
				} catch (_) {
					toast("收到无法解析的实时消息");
				}
			});
			socket.addEventListener("close", (event) => {
				const expected = state.expectedSocketClosures.has(socket);
				state.expectedSocketClosures.delete(socket);
				if (state.ws !== socket) return;
				state.ws = null;
				stopCountdown();
				setComposerBusy(false);
				if (expected) return;
				console.warn("调查连接中断", {
					gameId,
					code: event.code,
					reason: event.reason
				});
				if (event.code === 4401) showAuth();
				else if (event.code === 4404 || event.code === 4409) toast(event.reason || "案件存档无法恢复");
				else if (event.code !== 1e3) scheduleGameReconnect(gameId);
			});
		}
		function handleSocketMessage(message) {
			commandOutbox.acknowledge(message);
			const reduction = reduceRealtimeEnvelope(message, state.lastEventId);
			state.lastEventId = reduction.lastEventId;
			if (reduction.snapshotGame) renderGameInit(reduction.snapshotGame);
			reduction.messages.forEach(handleGameMessage);
			if (reduction.snapshotGame && state.ws?.readyState === WebSocket.OPEN) {
				const { commands, expiredCount } = commandOutbox.reconcile(commandContext());
				if (expiredCount) toast("阶段已变化，未确认的旧操作不再重发，请核对案件记录");
				for (const command of commands) state.ws.send(JSON.stringify(command));
				if (commands.some((command) => ["player_speech", "whisper_speech"].includes(command.type))) setComposerBusy(true);
			}
		}
		function scheduleGameReconnect(gameId) {
			if (!state.game || Number(state.game.id) !== Number(gameId)) return;
			if (state.reconnectTimer) return;
			if (state.reconnectAttempts >= 5) {
				toast("调查连接多次恢复失败，请返回案件档案后重试");
				return;
			}
			const delaySeconds = Math.min(10, 2 ** state.reconnectAttempts);
			state.reconnectAttempts += 1;
			toast(`调查连接已中断，${delaySeconds} 秒后自动恢复`);
			state.reconnectTimer = window.setTimeout(() => {
				state.reconnectTimer = null;
				if (!state.game || Number(state.game.id) !== Number(gameId)) return;
				connectGame(gameId, true);
			}, delaySeconds * 1e3);
		}
		function handleGameMessage(message) {
			switch (message.type) {
				case "heartbeat": break;
				case "game_init":
					renderGameInit(message);
					break;
				case "phase_changed":
					renderScenePhase(message.phase);
					break;
				case "dm_narration_start":
					beginNarration(message);
					break;
				case "dm_narration_chunk":
					appendNarration(message.content);
					break;
				case "dm_narration_end":
					finishNarration(message);
					loadNotebook(state.game?.id);
					break;
				case "private_script":
					renderPrivateAssignment(message);
					loadNotebook(state.game?.id);
					break;
				case "investigation_open":
					openInvestigation(message);
					break;
				case "human_speech_echo":
					setAvatarAction([message.role_id || state.game?.player_role_id], "public");
					addMessage("user", "你", message.content, {
						roleId: message.role_id || state.game?.player_role_id,
						action: "public",
						isHuman: true
					});
					break;
				case "ai_speech":
					clearAgentActivity();
					setAvatarAction([message.role_id], "public");
					addMessage("agent", message.proactive_response ? `${roleName(message.role_id)} · 回应 ${message.target_role_name || roleName(message.target_role_id)}` : roleName(message.role_id), message.content, {
						roleId: message.role_id,
						action: "public"
					});
					if (!message.proactive_response) setComposerBusy(false);
					loadNotebook(state.game?.id);
					break;
				case "agent_activity_start":
					showAgentActivity(message);
					break;
				case "ai_proactive_speech":
					clearAgentActivity();
					setAvatarAction([message.role_id], "public");
					addMessage("agent proactive", `${message.role_name || roleName(message.role_id)} · 主动询问 ${message.target_role_name || roleName(message.target_role_id)}`, message.content, {
						roleId: message.role_id,
						action: "public"
					});
					break;
				case "agent_private_exchange":
					clearAgentActivity();
					addMessage("dm ambient", "DM 动态", message.summary);
					break;
				case "autonomy_status":
					els.agentAutonomyState.classList.toggle("hidden", !message.autonomy?.enabled);
					break;
				case "speech_warning":
					addMessage("dm", "DM 校验", message.message);
					break;
				case "search_result":
					setAvatarAction([message.actor_role_id || state.game?.player_role_id], "search");
					addMessage("search", `搜证 · ${message.actor_role_name || roleName(message.actor_role_id || state.game?.player_role_id)}`, message.clue ? message.clue.content : message.message, {
						roleId: message.actor_role_id || state.game?.player_role_id,
						action: "search",
						isHuman: true
					});
					setCompactGamePanel("dialogue");
					loadNotebook(state.game?.id);
					break;
				case "clue_disclosed": {
					const privateShare = message.channel === "private";
					setAvatarAction([message.actor_role_id || state.game?.player_role_id, ...privateShare && message.target_role_id ? [message.target_role_id] : []], privateShare ? "private" : "public");
					const modeLabel = message.owner_view_mode === "distorted" ? "改写后分享" : "如实分享";
					addMessage(privateShare ? "user private" : "user", `你 · ${modeLabel}`, message.content, {
						roleId: message.actor_role_id || state.game?.player_role_id,
						action: privateShare ? "private" : "public",
						isHuman: true
					});
					loadNotebook(state.game?.id);
					break;
				}
				case "agent_search_result":
					clearAgentActivity();
					setAvatarAction([message.actor_role_id], "search");
					if (message.public_status === "shared_with_player") setAvatarAction([state.game?.player_role_id], "private");
					addMessage(message.public_status === "shared_with_player" ? "agent private" : "search", `搜证 · ${message.actor_role_name || roleName(message.actor_role_id)}`, message.summary, {
						roleId: message.actor_role_id,
						action: "search"
					});
					loadNotebook(state.game?.id);
					break;
				case "whisper_accepted":
					updateWhisperStatus({
						enabled: true,
						active_target_role_id: message.target_role_id,
						remaining_sessions: message.remaining_sessions
					});
					setChannel("private");
					addMessage("dm", "DM 私聊", `${message.target_role_name || roleName(message.target_role_id)}接受了私聊邀请。`);
					setCompactGamePanel("dialogue");
					break;
				case "whisper_declined":
					addMessage("dm", "DM 私聊", `${message.target_role_name || roleName(message.target_role_id)}拒绝了邀请：${message.message}`);
					setCompactGamePanel("dialogue");
					break;
				case "whisper_closed":
					addMessage("dm", "DM 私聊", message.target_role_id ? `与${message.target_role_name || roleName(message.target_role_id)}的私聊已结束。` : message.message);
					updateWhisperStatus({
						enabled: true,
						active_target_role_id: null
					});
					break;
				case "whisper_message":
					setAvatarAction([
						message.sender_role_id,
						message.conversation_role_id || state.whisper.activeTargetRoleId,
						state.game?.player_role_id
					], "private");
					addMessage(`${message.sender_type === "player" ? "user" : "agent"} private`, `${message.sender_type === "player" ? "你" : message.sender_role_name} · 私聊`, message.content, {
						roleId: message.sender_role_id,
						action: "private",
						isHuman: message.sender_type === "player"
					});
					if (message.sender_type === "agent") {
						setComposerBusy(false);
						loadNotebook(state.game?.id);
					}
					break;
				case "stage_advance":
					els.currentStage.textContent = String(message.stage);
					renderIntel(message.new_info);
					renderDispatch(message.dispatch);
					updateWhisperStatus(message.whisper_status);
					addMessage("dm", "DM Agent", `进入阶段 ${message.stage}，新情报已分别发放。`);
					setCompactGamePanel("intel");
					loadNotebook(state.game?.id);
					break;
				case "stage_resolution":
					renderStageResolution(message.resolution);
					break;
				case "investigation_progress":
					if (state.phaseSummary) {
						state.phaseSummary.end_condition = message.condition;
						state.phaseSummary.end_condition_text = message.end_condition_text;
						const penaltyText = (state.phaseSummary.player_penalties || []).map((penalty) => `${penalty.label}：${penalty.description}`).join("；");
						renderInvestigationRules(state.phaseSummary, penaltyText);
						if (state.currentPhase === "investigation" && message.condition?.met) els.advanceBtn.textContent = "建议目标已达成，发起结束投票";
					}
					break;
				case "investigation_end_vote":
					renderInvestigationEndVote(message.vote);
					addMessage("dm", "DM Agent", message.vote.message);
					toast(message.vote.message);
					if (!message.vote.approved) {
						els.advanceBtn.disabled = false;
						els.advanceBtn.textContent = "再次发起结束投票";
					}
					break;
				case "investigation_condition_met":
					addMessage("dm", "DM Agent", message.message);
					toast(message.message);
					break;
				case "replay":
					showReplay(message);
					break;
				case "hint":
					addMessage("dm", "DM 提示", message.content);
					break;
				case "error":
					clearAgentActivity();
					setComposerBusy(false);
					if (state.currentPhase === "investigation") renderScenePhase(state.phaseSummary);
					else {
						const labels = {
							briefing: "接收我的角色剧本",
							private_reveal: "我已阅读，进入调查",
							dm_hosting: "继续推进故事"
						};
						const resolutionPending = Boolean(state.stageResolution?.vote?.pending);
						if (resolutionPending) renderStageResolution(state.stageResolution);
						setPhaseContinue(resolutionPending ? "完成本幕投票后继续" : labels[state.currentPhase] || "重试", !resolutionPending);
					}
					toast(message.message);
			}
		}
		function renderGameInit(message) {
			state.game.publicRoles = message.public_roles;
			if (Array.isArray(message.history_events)) {
				els.messages.innerHTML = "";
				restoreEvents(message.history_events);
			}
			state.activeMechanics = message.active_mechanics || [];
			state.notebook.clues = message.clues || [];
			renderOwnedClues();
			els.currentStage.textContent = String(message.stage);
			els.totalStages.textContent = String(message.total_stages);
			els.humanRole.textContent = roleName(message.role_info.role_id);
			els.totalRoles.textContent = String(message.orchestration.total_roles);
			els.agentCount.textContent = String(message.orchestration.ai_agent_count);
			renderCast(message.public_roles, message.role_info.role_id);
			renderPhaseCast(message.public_roles, message.role_info.role_id);
			refreshRoleAvatars();
			renderDispatch(message.dispatch);
			renderScenePhase(message.phase);
			if (message.phase?.phase !== "investigation") {
				renderIntel([]);
				resetWhisper();
				applyActionAvailability();
			}
			const completed = state.game?.status === "completed";
			els.advanceBtn.disabled = completed;
			if (completed) els.advanceBtn.textContent = "本局已完成";
		}
		function renderIntel(blocks) {
			els.playerIntel.innerHTML = "";
			if (!blocks || !blocks.length) {
				els.playerIntel.innerHTML = "<div class=\"intel-item\">本阶段没有新增私人情报</div>";
				return;
			}
			blocks.forEach((block) => {
				const item = document.createElement("div");
				item.className = "intel-item";
				item.textContent = block.content;
				els.playerIntel.appendChild(item);
			});
		}
		function renderSearchTargets(mechanics) {
			els.searchTargets.innerHTML = "";
			if (!state.enabledActions.includes("search")) {
				els.searchTargets.innerHTML = "<div class=\"intel-item\">本幕未开放现场搜证</div>";
				return;
			}
			const action = (mechanics || []).flatMap((item) => item.actions || []).find((item) => item.type === "search");
			const currentStage = Number(state.phaseSummary?.stage || 1);
			(action?.targets || []).filter((target) => Number(target.unlock_stage || 1) <= currentStage).forEach((target) => {
				const button = document.createElement("button");
				button.type = "button";
				button.className = "search-button";
				button.textContent = target.name;
				button.addEventListener("click", () => {
					if (sendGame({
						type: "search",
						target_id: target.id
					})) {
						setAvatarAction([state.game?.player_role_id], "search");
						setCompactGamePanel("dialogue");
					}
				});
				els.searchTargets.appendChild(button);
			});
			if (!els.searchTargets.children.length) els.searchTargets.innerHTML = "<div class=\"intel-item\">本剧本未启用搜证</div>";
		}
		function renderWhisperControls(mechanics, roles, humanRoleId, status) {
			const action = (mechanics || []).flatMap((item) => item.actions || []).find((item) => item.type === "whisper_invite");
			const enabled = Boolean(action) && state.enabledActions.includes("whisper");
			state.whisper.enabled = enabled;
			els.whisperSection.classList.toggle("hidden", !enabled);
			els.channelControl.classList.toggle("hidden", !enabled);
			if (!enabled) {
				updateWhisperStatus({
					enabled: false,
					active_target_role_id: null
				});
				return;
			}
			els.whisperTarget.innerHTML = "";
			roles.filter((role) => role.role_id !== humanRoleId).forEach((role) => {
				const option = document.createElement("option");
				option.value = role.role_id;
				option.textContent = role.role_name;
				els.whisperTarget.appendChild(option);
			});
			updateWhisperStatus(status);
		}
		function updateWhisperStatus(status = {}) {
			const activeTarget = status.active_target_role_id || null;
			state.whisper.activeTargetRoleId = activeTarget;
			els.whisperTarget.disabled = Boolean(activeTarget);
			els.whisperInviteBtn.classList.toggle("hidden", Boolean(activeTarget));
			els.whisperCloseBtn.classList.toggle("hidden", !activeTarget);
			els.privateChannelBtn.disabled = !activeTarget;
			if (activeTarget) {
				els.whisperTarget.value = activeTarget;
				const remaining = Number.isInteger(status.remaining_sessions) ? `，本阶段还可发起 ${status.remaining_sessions} 次` : "";
				els.whisperStatus.textContent = `正在与${roleName(activeTarget)}私聊${remaining}`;
				renderConversationParticipants(activeTarget);
			} else {
				els.whisperStatus.textContent = status.enabled === false ? "本剧本未启用私聊" : "选择一个角色发出邀请";
				renderConversationParticipants(null);
				setChannel("public");
			}
			renderOwnedClues();
		}
		function setChannel(channel) {
			if (channel === "private" && !state.whisper.activeTargetRoleId) return;
			state.whisper.channel = channel;
			els.publicChannelBtn.classList.toggle("active", channel === "public");
			els.privateChannelBtn.classList.toggle("active", channel === "private");
			if (channel === "private") {
				const targetName = roleName(state.whisper.activeTargetRoleId);
				els.channelTarget.textContent = `仅你、${targetName}和 DM 可见`;
				els.speechInput.placeholder = `私聊 ${targetName}`;
			} else {
				els.channelTarget.textContent = "当前为公开频道";
				els.speechInput.placeholder = "以角色身份公开发言";
			}
			const enabled = state.currentPhase === "investigation" && (channel === "private" ? state.enabledActions.includes("whisper") && Boolean(state.whisper.activeTargetRoleId) : state.enabledActions.includes("public_speech"));
			els.speechInput.disabled = state.waitingForAgent || !enabled;
			els.speechSubmitBtn.disabled = state.waitingForAgent || !enabled;
			els.speechForm.classList.toggle("action-locked", !enabled);
		}
		function resetWhisper() {
			state.whisper.enabled = false;
			state.whisper.activeTargetRoleId = null;
			state.whisper.channel = "public";
			els.whisperSection.classList.add("hidden");
			els.channelControl.classList.add("hidden");
			setChannel("public");
		}
		function renderCast(roles, humanRoleId) {
			els.castList.innerHTML = "";
			roles.forEach((role) => {
				const item = document.createElement("div");
				item.className = "cast-item";
				const isHuman = role.role_id === humanRoleId;
				item.innerHTML = `${roleAvatarMarkup(role.role_id, role.role_name, {
					isHuman,
					size: "small",
					live: true
				})}<div><strong>${escapeHtml(role.role_name)}</strong><span>${escapeHtml(role.public_identity)}</span></div><span class="cast-tag">${isHuman ? "玩家" : "Agent"}</span>`;
				els.castList.appendChild(item);
			});
		}
		function renderDispatch(dispatch) {
			els.dispatchList.innerHTML = "";
			(dispatch?.deliveries || []).forEach((delivery) => {
				const item = document.createElement("div");
				item.className = "dispatch-item";
				item.innerHTML = `<span>${escapeHtml(delivery.role_name)}</span><strong>${delivery.block_count} 条</strong>`;
				els.dispatchList.appendChild(item);
			});
		}
		function resetNotebook() {
			if (state.notebook.saveTimer) window.clearTimeout(state.notebook.saveTimer);
			state.notebook.automatic = [];
			state.notebook.clues = [];
			state.notebook.manualNotes = "";
			state.notebook.activeSection = "automatic";
			state.notebook.saveTimer = null;
			state.notebook.dirty = false;
			if (!els.notebookAutoEntries) return;
			els.notebookAutoEntries.innerHTML = "<div class=\"notebook-empty\">等待 DM 归档信息</div>";
			els.ownedClues.innerHTML = "<div class=\"notebook-empty\">尚未获得私有搜证线索</div>";
			els.notebookManualNotes.value = "";
			els.notebookSaveState.textContent = "输入内容后自动保存";
			setNotebookSection("automatic");
		}
		function setNotebookSection(section) {
			if (![
				"automatic",
				"clues",
				"manual"
			].includes(section)) return;
			state.notebook.activeSection = section;
			const automatic = section === "automatic";
			const clues = section === "clues";
			const manual = section === "manual";
			els.notebookAutoTab.classList.toggle("active", automatic);
			els.notebookCluesTab.classList.toggle("active", clues);
			els.notebookManualTab.classList.toggle("active", manual);
			els.notebookAutoTab.setAttribute("aria-selected", String(automatic));
			els.notebookCluesTab.setAttribute("aria-selected", String(clues));
			els.notebookManualTab.setAttribute("aria-selected", String(manual));
			els.notebookAutoPane.classList.toggle("hidden", !automatic);
			els.notebookCluesPane.classList.toggle("hidden", !clues);
			els.notebookManualPane.classList.toggle("hidden", !manual);
		}
		async function loadNotebook(gameId) {
			if (!gameId || state.game?.id !== gameId) return;
			try {
				const notebook = await api(`/api/games/${gameId}/notebook`);
				if (state.game?.id !== gameId) return;
				state.notebook.automatic = notebook.automatic || [];
				state.notebook.clues = notebook.clues || [];
				renderNotebookEntries();
				renderOwnedClues();
				if (!state.notebook.dirty) {
					state.notebook.manualNotes = notebook.manual_notes || "";
					els.notebookManualNotes.value = state.notebook.manualNotes;
					els.notebookSaveState.textContent = notebook.manual_updated_at ? "已保存" : "输入内容后自动保存";
				}
			} catch (error) {
				if (state.game?.id === gameId) els.notebookAutoEntries.innerHTML = `<div class="notebook-empty">${escapeHtml(error.message)}</div>`;
			}
		}
		function renderNotebookEntries() {
			els.notebookAutoEntries.innerHTML = "";
			if (!state.notebook.automatic.length) {
				els.notebookAutoEntries.innerHTML = "<div class=\"notebook-empty\">暂无自动归档线索</div>";
				return;
			}
			state.notebook.automatic.forEach((entry) => {
				const item = document.createElement("article");
				item.className = "notebook-entry";
				item.innerHTML = `
      <span>${escapeHtml(notebookStageLabel(entry))} · ${escapeHtml(notebookSourceLabel(entry.source_type))}</span>
      <strong>${escapeHtml(entry.title)}</strong>
      <p>${escapeHtml(entry.content)}</p>`;
				els.notebookAutoEntries.appendChild(item);
			});
		}
		function renderOwnedClues() {
			if (!els.ownedClues) return;
			els.ownedClues.innerHTML = "";
			if (!state.notebook.clues.length) {
				els.ownedClues.innerHTML = "<div class=\"notebook-empty\">尚未获得私有搜证线索</div>";
				return;
			}
			const canShare = state.currentPhase === "investigation";
			state.notebook.clues.forEach((clue) => {
				const item = document.createElement("article");
				item.className = `owned-clue ${clue.disclosure_mode || "private"}`;
				const status = {
					private: "仅你与 DM 知道",
					truthful: "最近一次已如实分享",
					distorted: "最近一次使用了改写说法"
				}[clue.disclosure_mode] || "仅你与 DM 知道";
				const audienceOptions = ["<option value=\"public\">公开给所有人</option>"];
				if (state.whisper.activeTargetRoleId) audienceOptions.push(`<option value="private:${escapeHtml(state.whisper.activeTargetRoleId)}">私下给 ${escapeHtml(roleName(state.whisper.activeTargetRoleId))}</option>`);
				const previousDisclosure = clue.shared_content ? `<div class="clue-previous-claim"><span>已发布说法</span><p>${escapeHtml(clue.shared_content)}</p></div>` : "";
				item.innerHTML = `
      <header>
        <span>ACT ${String(clue.stage).padStart(2, "0")} · ${escapeHtml(clue.target_name)}</span>
        <b>${escapeHtml(status)}</b>
      </header>
      <p class="clue-truth">${escapeHtml(clue.truth_content)}</p>
      ${previousDisclosure}
      <label class="clue-audience">
        <span>分享范围</span>
        <select aria-label="选择线索分享范围">${audienceOptions.join("")}</select>
      </label>
      <div class="clue-share-actions">
        <button type="button" data-clue-action="truthful" ${canShare ? "" : "disabled"}>如实分享</button>
        <button type="button" data-clue-action="distort" ${canShare ? "" : "disabled"}>改写后分享</button>
      </div>
      <div class="clue-distort-editor hidden">
        <textarea maxlength="300" placeholder="输入你准备让其他角色相信的说法..."></textarea>
        <div>
          <button type="button" data-clue-action="publish-distorted">发布说法</button>
          <button class="icon-button" type="button" data-clue-action="cancel-distorted" title="取消改写" aria-label="取消改写">×</button>
        </div>
      </div>`;
				item.querySelector("[data-clue-action=\"truthful\"]").addEventListener("click", () => shareOwnedClue(clue, "truthful", item));
				item.querySelector("[data-clue-action=\"distort\"]").addEventListener("click", () => {
					item.querySelector(".clue-distort-editor").classList.remove("hidden");
					item.querySelector(".clue-distort-editor textarea").focus();
				});
				item.querySelector("[data-clue-action=\"cancel-distorted\"]").addEventListener("click", () => {
					item.querySelector(".clue-distort-editor").classList.add("hidden");
				});
				item.querySelector("[data-clue-action=\"publish-distorted\"]").addEventListener("click", () => shareOwnedClue(clue, "distorted", item));
				els.ownedClues.appendChild(item);
			});
		}
		function shareOwnedClue(clue, mode, item) {
			const [scope, targetRoleId] = item.querySelector(".clue-audience select").value.split(":");
			const content = mode === "distorted" ? item.querySelector(".clue-distort-editor textarea").value.trim() : "";
			if (mode === "distorted" && content.length < 2) {
				toast("先写下至少 2 个字符的对外说法");
				return;
			}
			sendGame({
				type: "share_clue",
				clue_id: clue.clue_id,
				mode,
				content,
				scope,
				target_role_id: targetRoleId || null
			});
		}
		function notebookSourceLabel(sourceType) {
			return {
				story_background: "案件背景",
				public_briefing: "DM 公开通报",
				public_tasks: "DM 公开任务",
				public_information: "DM 公开信息",
				dm_hosting: "DM 主持归档",
				dm_narration: "DM 公布",
				role_script: "角色剧本",
				personal_task: "个人任务",
				search: "现场搜证",
				clue_claim: "线索声明",
				clue_disclosure: "线索披露",
				public_conversation: "公开交流",
				private_conversation: "私下交流",
				agent_hypothesis: "推理结论",
				manual: "玩家手记",
				public_speech: "公开发言",
				public_response: "公开回应",
				autonomous_public_speech: "主动公开询问",
				autonomous_public_response: "主动公开回应",
				private_speech: "私聊发言",
				private_response: "私聊回应",
				autonomous_private_speech: "主动私聊",
				autonomous_private_response: "主动私聊回应",
				whisper_accepted: "接受私聊",
				whisper_declined: "拒绝私聊",
				whisper_closed: "结束私聊",
				stage_resolution: "阶段结算",
				stage_vote: "阶段投票",
				final_vote: "最终指认"
			}[sourceType] || sourceType;
		}
		function queueManualNotebookSave() {
			const gameId = state.game?.id;
			if (!gameId) return;
			const content = els.notebookManualNotes.value;
			state.notebook.manualNotes = content;
			state.notebook.dirty = true;
			els.notebookSaveState.textContent = "等待保存";
			if (state.notebook.saveTimer) window.clearTimeout(state.notebook.saveTimer);
			state.notebook.saveTimer = window.setTimeout(() => saveManualNotebook(gameId, content), 650);
		}
		async function saveManualNotebook(gameId, content) {
			if (!gameId) return;
			els.notebookSaveState.textContent = "保存中";
			try {
				await api(`/api/games/${gameId}/notebook/manual`, {
					method: "PUT",
					body: JSON.stringify({ content })
				});
				if (state.game?.id === gameId && els.notebookManualNotes.value === content) {
					state.notebook.dirty = false;
					els.notebookSaveState.textContent = "已保存";
				}
			} catch (error) {
				if (state.game?.id === gameId) {
					els.notebookSaveState.textContent = "保存失败";
					toast(error.message);
				}
			}
		}
		async function openRoleRecords() {
			const gameId = state.game?.id;
			if (!gameId) return;
			try {
				const records = await api(`/api/games/${gameId}/role-records`);
				state.roleRecords = records;
				els.auditRoleTabs.innerHTML = "";
				records.roles.forEach((role, index) => {
					const button = document.createElement("button");
					button.type = "button";
					button.role = "tab";
					button.innerHTML = `
        <span>${role.controller === "human" ? "PLAYER" : "AGENT"}</span>
        <strong>${escapeHtml(role.role_name)}</strong>`;
					button.addEventListener("click", () => renderRoleRecord(role.role_id));
					els.auditRoleTabs.appendChild(button);
					if (index === 0) button.classList.add("active");
				});
				if (records.roles.length) renderRoleRecord(records.roles[0].role_id);
				els.roleRecordsModal.classList.remove("hidden");
				document.body.classList.add("modal-open");
			} catch (error) {
				toast(error.message);
			}
		}
		function renderRoleRecord(roleId) {
			const role = state.roleRecords?.roles?.find((item) => item.role_id === roleId);
			if (!role) return;
			[...els.auditRoleTabs.children].forEach((button, index) => {
				const selected = state.roleRecords.roles[index]?.role_id === roleId;
				button.classList.toggle("active", selected);
				button.setAttribute("aria-selected", String(selected));
			});
			renderAuditClues(role.clues || []);
			renderAuditEntries(els.auditAutomaticEntries, role.automatic_notebook, "该角色没有自动线索记录");
			renderAuditEntries(els.auditReasoningEntries, role.reasoning_notebook, "该角色没有留下推理记录");
			renderAuditStageResults(role.stage_results || []);
			renderAgentContextAudits(role.agent_context_audits || []);
			els.auditOperations.innerHTML = "";
			if (!role.operations.length) els.auditOperations.innerHTML = "<div class=\"audit-empty\">该角色没有执行操作</div>";
			else role.operations.forEach((operation) => {
				const item = document.createElement("article");
				item.innerHTML = `
        <span>ACT ${String(operation.stage).padStart(2, "0")} · ${escapeHtml(operation.channel)}</span>
        <strong>${escapeHtml(notebookSourceLabel(operation.event_type))}</strong>
        <p>${escapeHtml(operation.summary)}</p>`;
				els.auditOperations.appendChild(item);
			});
		}
		function renderAgentContextAudits(audits) {
			els.auditAgentContexts.innerHTML = "";
			if (!audits.length) {
				els.auditAgentContexts.innerHTML = "<div class=\"audit-empty\">该角色没有 Agent 调用记录</div>";
				return;
			}
			audits.forEach((audit) => {
				const context = audit.context || {};
				const messages = Array.isArray(context.messages) ? context.messages : [];
				const transcript = [`[SYSTEM · ROLE PRIVATE]\n${context.system_prompt || ""}`, ...messages.map((message) => `[${String(message.scope || "unknown").toUpperCase()} · ${message.source_type || "unknown"}]\n${message.role || "user"}: ${message.content || ""}`)].join("\n\n");
				const item = document.createElement("article");
				item.classList.toggle("failed", audit.status !== "completed");
				item.innerHTML = `
      <span>ACT ${String(audit.stage).padStart(2, "0")} · ${escapeHtml(audit.channel)}</span>
      <strong>${escapeHtml(audit.purpose)} · ${escapeHtml({
					completed: "已完成",
					failed: "调用失败",
					canceled: "已取消",
					running: "结果待确认"
				}[audit.status] || "未知状态")}</strong>
      <p>${escapeHtml(context.prompt_version || "旧版记录")} · ${context.latency_ms == null ? "耗时未记录" : `${escapeHtml(context.latency_ms)} ms`} · ${context.input_tokens == null ? "用量未返回" : `输入 ${escapeHtml(context.input_tokens)} / 输出 ${escapeHtml(context.output_tokens ?? "未知")} tokens`}${audit.gameplay_committed === false ? " · 游戏结果未提交" : ""}</p>
      <details>
        <summary>${context.input_prepared === false ? "查看输入准备记录" : "查看实际输入"} · ${messages.length + 1} 段</summary>
        <pre>${escapeHtml(transcript)}</pre>
      </details>
      ${audit.error ? `<p>${escapeHtml(audit.error)}</p>` : ""}`;
				els.auditAgentContexts.appendChild(item);
			});
		}
		function renderAuditStageResults(stageResults) {
			els.auditStageResults.innerHTML = "";
			if (!stageResults.length) return;
			stageResults.forEach((stageResult) => {
				const result = stageResult.result;
				if (!result) return;
				const metric = stageResult.metric || {
					label: "阶段成果",
					unit: ""
				};
				const vote = stageResult.vote;
				const item = document.createElement("article");
				item.innerHTML = `
      <span>ACT ${String(stageResult.stage).padStart(2, "0")} · STAGE SETTLEMENT</span>
      <strong>${escapeHtml(stageResult.title)}</strong>
      <p>本幕 ${Number(result.delta) >= 0 ? "+" : ""}${escapeHtml(result.delta)} ${escapeHtml(metric.unit)}，累计${escapeHtml(metric.label)} ${escapeHtml(result.total)} ${escapeHtml(metric.unit)}。${vote?.outcome_text ? `\n${escapeHtml(vote.outcome_text)}` : ""}</p>${taskResultMarkup(result.task_results)}`;
				els.auditStageResults.appendChild(item);
			});
		}
		function taskResultMarkup(tasks) {
			const labels = {
				completed: "已完成",
				failed: "未完成",
				manual_review: "需人工评审"
			};
			if (!Array.isArray(tasks) || !tasks.length) return "";
			return `<ul class="task-results">${tasks.map((task) => `<li>
    <span>${escapeHtml(task.label)}</span><strong>${escapeHtml(labels[task.status] || "待判定")}</strong>
    ${task.description ? `<p>${escapeHtml(task.description)}</p>` : ""}
    ${task.minimum ? `<small>${escapeHtml(task.count)} / ${escapeHtml(task.minimum)}</small>` : ""}
  </li>`).join("")}</ul>`;
		}
		function renderAuditClues(clues) {
			els.auditClues.innerHTML = "";
			if (!clues.length) {
				els.auditClues.innerHTML = "<div class=\"audit-empty\">该角色没有取得搜证线索</div>";
				return;
			}
			clues.forEach((clue) => {
				const modeLabel = {
					private: "全程保密",
					truthful: "如实披露",
					distorted: "扭曲披露"
				}[clue.disclosure_mode] || "全程保密";
				const audience = clue.shared_scope === "public" ? "公开给所有角色" : clue.target_role_id ? `私下给 ${roleName(clue.target_role_id)}` : "未对外分享";
				const claim = clue.shared_content ? `<div class="audit-claim"><span>对外说法</span><p>${escapeHtml(clue.shared_content)}</p></div>` : "<div class=\"audit-claim muted\"><span>对外说法</span><p>未分享</p></div>";
				const item = document.createElement("article");
				item.className = `audit-clue ${clue.disclosure_mode || "private"}`;
				item.innerHTML = `
      <span>ACT ${String(clue.stage).padStart(2, "0")} · ${escapeHtml(clue.target_name)}</span>
      <strong>${escapeHtml(modeLabel)} · ${escapeHtml(audience)}</strong>
      <div class="audit-truth"><span>DM 原始线索</span><p>${escapeHtml(clue.truth_content)}</p></div>
      ${claim}`;
				els.auditClues.appendChild(item);
			});
		}
		function renderAuditEntries(container, entries, emptyText) {
			container.innerHTML = "";
			if (!entries?.length) {
				container.innerHTML = `<div class="audit-empty">${escapeHtml(emptyText)}</div>`;
				return;
			}
			entries.forEach((entry) => {
				const item = document.createElement("article");
				item.innerHTML = `
      <span>${escapeHtml(notebookStageLabel(entry))} · ${escapeHtml(notebookSourceLabel(entry.source_type))}</span>
      <strong>${escapeHtml(entry.title)}</strong>
      <p>${escapeHtml(entry.content)}</p>`;
				container.appendChild(item);
			});
		}
		function notebookStageLabel(entry) {
			if (!Number.isInteger(entry.stage) || entry.stage < 1) return "幕次未记录";
			return `ACT ${String(entry.stage).padStart(2, "0")}${entry.phase === "replay" ? " · 终局修订" : ""}`;
		}
		function closeRoleRecords() {
			if (!els.roleRecordsModal) return;
			els.roleRecordsModal.classList.add("hidden");
			document.body.classList.remove("modal-open");
		}
		function restoreEvents(events) {
			events.forEach((event) => {
				const payload = event.payload || {};
				if (event.type === "human_speech_echo") addMessage("user", "你", payload.content, {
					roleId: payload.role_id || state.game?.player_role_id,
					action: "public",
					isHuman: true
				});
				if (event.type === "ai_speech") addMessage("agent", roleName(payload.role_id), payload.content, {
					roleId: payload.role_id,
					action: "public"
				});
				if (event.type === "ai_proactive_speech") addMessage("agent proactive", `${payload.role_name || payload.role_id} · 主动询问 ${payload.target_role_name || payload.target_role_id}`, payload.content, {
					roleId: payload.role_id,
					action: "public"
				});
				if (event.type === "agent_private_exchange") addMessage("dm ambient", "DM 动态", payload.summary);
				if (event.type === "search_result" && payload.clue) addMessage("search", `搜证 · ${payload.actor_role_name || roleName(payload.actor_role_id || state.game?.player_role_id)}`, payload.clue.content, {
					roleId: payload.actor_role_id || state.game?.player_role_id,
					action: "search",
					isHuman: true
				});
				if (event.type === "whisper_accepted") addMessage("dm", "DM 私聊", `${payload.target_role_name || payload.target_role_id}接受了私聊邀请`);
				if (event.type === "whisper_declined") addMessage("dm", "DM 私聊", payload.message);
				if (event.type === "whisper_closed" && payload.target_role_id) addMessage("dm", "DM 私聊", `与${payload.target_role_name || payload.target_role_id}的私聊已结束`);
				if (event.type === "whisper_message") addMessage(`${payload.sender_type === "player" ? "user" : "agent"} private`, `${payload.sender_type === "player" ? "你" : payload.sender_role_name || payload.sender_role_id} · 私聊`, payload.content, {
					roleId: payload.sender_role_id,
					action: "private",
					isHuman: payload.sender_type === "player"
				});
				if (event.type === "stage_advance") addMessage("dm", "DM Agent", `已进入阶段 ${payload.stage}`);
				if (event.type === "replay") addMessage("dm", "终局复盘", payload.full_story);
			});
		}
		function addMessage(type, speaker, content, options = {}) {
			if (!content) return null;
			const item = document.createElement("article");
			item.className = `message ${type}`;
			item.innerHTML = `
    <div class="message-avatar-wrap">
      ${roleAvatarMarkup(options.roleId || "dm", options.avatarLabel || speaker, {
				isHuman: Boolean(options.isHuman),
				action: options.action || (type.includes("private") ? "private" : "")
			})}
    </div>
    <div class="message-body">
      <span class="speaker">${escapeHtml(speaker)}</span>
      <div class="content">${escapeHtml(content)}</div>
    </div>`;
			els.messages.appendChild(item);
			els.messages.scrollTop = els.messages.scrollHeight;
			return item;
		}
		function showAgentActivity(message) {
			clearAgentActivity();
			setAvatarAction([message.actor_role_id, message.target_role_id], message.channel === "private" ? "private" : "public");
			if (!message.target_role_id) {
				state.agentActivityNode = addMessage("agent activity", "角色正在自主行动", `${message.actor_role_name || roleName(message.actor_role_id)}正在评估线索并选择交流对象...`, {
					roleId: message.actor_role_id,
					avatarLabel: message.actor_role_name,
					action: "public"
				});
				return;
			}
			const channel = message.channel === "private" ? "私下接触" : "公开询问";
			state.agentActivityNode = addMessage("agent activity", "角色正在自主行动", `${message.actor_role_name || roleName(message.actor_role_id)}正在${channel}${message.target_role_name || roleName(message.target_role_id)}...`, {
				roleId: message.actor_role_id,
				avatarLabel: message.actor_role_name,
				action: message.channel === "private" ? "private" : "public"
			});
		}
		function clearAgentActivity() {
			if (state.agentActivityNode?.isConnected) state.agentActivityNode.remove();
			state.agentActivityNode = null;
		}
		function roleName(roleId) {
			return state.game?.publicRoles?.find((role) => role.role_id === roleId)?.role_name || roleId;
		}
		function roleAvatarMarkup(roleId, label, options = {}) {
			const normalizedRoleId = String(roleId || "dm");
			const normalizedLabel = String(label || roleName(normalizedRoleId) || "DM");
			const identityLabel = state.game?.publicRoles?.find((role) => role.role_id === normalizedRoleId)?.role_name || normalizedLabel.split("·", 1)[0].trim() || normalizedLabel;
			const initial = normalizedRoleId === "dm" ? "DM" : [...identityLabel.replace(/\s/g, "")].slice(-1).join("") || "?";
			return `
    <span class="${[
				"role-avatar",
				`avatar-tone-${avatarTone(normalizedRoleId)}`,
				options.size === "small" ? "role-avatar-small" : "",
				options.isHuman ? "role-avatar-human" : "",
				options.action ? `avatar-${options.action}` : "",
				options.session ? "avatar-private-session" : ""
			].filter(Boolean).join(" ")}" data-role-avatar="${escapeHtml(normalizedRoleId)}"${options.live ? " data-avatar-live=\"true\"" : ""} title="${escapeHtml(normalizedLabel)}">
      <i aria-hidden="true"></i><b>${escapeHtml(initial)}</b><em aria-hidden="true"></em>
    </span>`;
		}
		function avatarTone(roleId) {
			let hash = 0;
			for (const character of String(roleId || "")) hash = (hash << 5) - hash + character.codePointAt(0) | 0;
			return Math.abs(hash) % 5;
		}
		function setAvatarAction(roleIds, action, duration = 1450) {
			const ids = new Set(roleIds.filter(Boolean).map(String));
			if (!ids.size) return;
			document.querySelectorAll("[data-role-avatar][data-avatar-live=\"true\"]").forEach((avatar) => {
				if (!ids.has(avatar.dataset.roleAvatar)) return;
				const previousTimer = avatarActionTimers.get(avatar);
				if (previousTimer) window.clearTimeout(previousTimer);
				avatar.classList.remove("avatar-public", "avatar-private", "avatar-search");
				avatar.offsetWidth;
				avatar.classList.add(`avatar-${action}`);
				const timer = window.setTimeout(() => {
					if (avatar.isConnected) avatar.classList.remove(`avatar-${action}`);
					avatarActionTimers.delete(avatar);
				}, duration);
				avatarActionTimers.set(avatar, timer);
			});
		}
		function refreshRoleAvatars() {
			document.querySelectorAll("[data-role-avatar]").forEach((avatar) => {
				const roleId = avatar.dataset.roleAvatar;
				if (!roleId || roleId === "dm") return;
				const name = roleName(roleId);
				if (!name || name === roleId) return;
				const initial = [...name.replace(/\s/g, "")].slice(-1).join("");
				const label = avatar.querySelector("b");
				if (label && initial) label.textContent = initial;
				avatar.title = name;
			});
		}
		function renderConversationParticipants(targetRoleId) {
			if (!els.conversationParticipants) return;
			if (!targetRoleId) {
				els.conversationParticipants.classList.add("hidden");
				els.conversationParticipants.innerHTML = "";
				return;
			}
			const humanRoleId = state.game?.player_role_id;
			els.conversationParticipants.innerHTML = `
    ${roleAvatarMarkup(humanRoleId, roleName(humanRoleId), {
				isHuman: true,
				size: "small",
				session: true,
				live: true
			})}
    <span><i></i><b>PRIVATE</b><i></i></span>
    ${roleAvatarMarkup(targetRoleId, roleName(targetRoleId), {
				size: "small",
				session: true,
				live: true
			})}`;
			els.conversationParticipants.classList.remove("hidden");
		}
		function sendGame(payload) {
			if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
				toast("游戏连接尚未就绪");
				return false;
			}
			const command = buildCommandEnvelope(Number(state.game.id), payload);
			try {
				commandOutbox.retain(command, commandContext());
				state.ws.send(JSON.stringify(command));
			} catch (error) {
				toast(error.message || "操作尚未发送，请稍后重试");
				return false;
			}
			return true;
		}
		function commandContext() {
			return {
				gameId: Number(state.game.id),
				stage: Number(state.phaseSummary?.stage || 1),
				phase: state.currentPhase
			};
		}
		function closeGameSocket() {
			commandOutbox.clear();
			if (state.reconnectTimer) window.clearTimeout(state.reconnectTimer);
			state.reconnectTimer = null;
			state.reconnectAttempts = 0;
			if (state.ws) {
				state.expectedSocketClosures.add(state.ws);
				state.ws.close();
			}
			state.ws = null;
			stopCountdown();
			clearAgentActivity();
			setComposerBusy(false);
		}
		function setComposerBusy(busy) {
			state.waitingForAgent = busy;
			const actionEnabled = state.currentPhase === "investigation" && (state.whisper.channel === "private" ? state.enabledActions.includes("whisper") && Boolean(state.whisper.activeTargetRoleId) : state.enabledActions.includes("public_speech"));
			els.speechInput.disabled = busy || !actionEnabled;
			els.speechSubmitBtn.disabled = busy || !actionEnabled;
			els.speechSubmitBtn.textContent = busy ? "整理中" : "发送";
			if (busy) els.speechInput.placeholder = "角色正在整理证词...";
			else if (!actionEnabled) els.speechInput.placeholder = state.currentPhase === "investigation" ? "本幕未开放当前询问方式" : "等待 DM 开放调查";
			else setChannel(state.whisper.channel);
		}
		let toastTimer;
		function toast(message) {
			els.toast.textContent = message;
			els.toast.classList.add("show");
			clearTimeout(toastTimer);
			toastTimer = setTimeout(() => els.toast.classList.remove("show"), 2600);
		}
		function escapeHtml(value) {
			const node = document.createElement("div");
			node.textContent = String(value ?? "");
			return node.innerHTML;
		}
		function animateView(element) {
			element.classList.remove("view-enter");
			requestAnimationFrame(() => element.classList.add("view-enter"));
			window.setTimeout(() => element.classList.remove("view-enter"), 500);
		}
		const glassInteractiveSelector = [
			"button",
			".role-option",
			".upload-zone"
		].join(",");
		document.addEventListener("pointerdown", (event) => {
			const target = event.target.closest(glassInteractiveSelector);
			if (!target || target.matches(":disabled")) return;
			const rect = target.getBoundingClientRect();
			const x = (event.clientX - rect.left) / Math.max(rect.width, 1) * 100;
			const y = (event.clientY - rect.top) / Math.max(rect.height, 1) * 100;
			target.style.setProperty("--press-x", `${x}%`);
			target.style.setProperty("--press-y", `${y}%`);
			target.classList.remove("glass-pressed");
			requestAnimationFrame(() => target.classList.add("glass-pressed"));
			window.setTimeout(() => target.classList.remove("glass-pressed"), 680);
		});
		appEvents.on("auth:authenticated", ({ user }) => {
			enterApp(user).catch((error) => toast(error.message || "进入调查室失败"));
		});
		appEvents.on("auth:logout", ({ preserveReturnPath, broadcast }) => {
			showAuth(preserveReturnPath);
			if (broadcast) authChannel?.postMessage({ type: "logout" });
		});
		appEvents.on("navigation:view", ({ view }) => showPage(view));
		appEvents.on("sidebar:set", ({ collapsed, focusTarget }) => {
			setSidebarCollapsed(collapsed, focusTarget);
		});
		appEvents.on("records:open", ({ gameId }) => {
			openGame(gameId);
		});
		appEvents.on("records:deleted", ({ gameId, title }) => {
			if (state.game?.id === gameId) {
				state.game = null;
				state.roleRecords = null;
				resetNotebook();
			}
			toast(`已删除案件“${title}”`);
		});
		appEvents.on("toast:show", ({ message }) => toast(message));
		els.expandSidebarBtn.addEventListener("click", () => setSidebarCollapsed(false, true));
		document.querySelectorAll(".compact-game-tab").forEach((button) => {
			button.addEventListener("click", () => setCompactGamePanel(button.dataset.panel));
			button.addEventListener("keydown", (event) => {
				if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
				event.preventDefault();
				const tabs = [...document.querySelectorAll(".compact-game-tab")];
				const next = tabs[(tabs.indexOf(button) + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
				setCompactGamePanel(next.dataset.panel);
				next.focus();
			});
		});
		compactGameMedia.addEventListener("change", syncCompactGamePanel);
		els.chooseFileBtn.addEventListener("click", () => els.scriptFileInput.click());
		els.uploadZone.addEventListener("dblclick", () => els.scriptFileInput.click());
		els.uploadZone.addEventListener("keydown", (event) => {
			if (event.key === "Enter") els.scriptFileInput.click();
		});
		els.scriptFileInput.addEventListener("change", () => readScriptFile(els.scriptFileInput.files[0]));
		for (const eventName of ["dragenter", "dragover"]) els.uploadZone.addEventListener(eventName, (event) => {
			event.preventDefault();
			els.uploadZone.classList.add("dragging");
		});
		for (const eventName of ["dragleave", "drop"]) els.uploadZone.addEventListener(eventName, (event) => {
			event.preventDefault();
			els.uploadZone.classList.remove("dragging");
		});
		els.uploadZone.addEventListener("drop", (event) => readScriptFile(event.dataTransfer.files[0]));
		els.exampleScriptBtn.addEventListener("click", async () => {
			try {
				const preview = await api("/api/scripts/example");
				state.script = null;
				state.builtinScriptId = preview.script_id;
				els.uploadTitle.textContent = "fog_harbor_clocktower.json";
				els.uploadMeta.textContent = "内置悬疑案件 · JSON";
				await inspectScript();
			} catch (error) {
				els.scriptError.textContent = error.message;
			}
		});
		els.startGameBtn.addEventListener("click", startGame);
		els.leaveGameBtn.addEventListener("click", () => showPage("records"));
		els.notebookAutoTab.addEventListener("click", () => setNotebookSection("automatic"));
		els.notebookCluesTab.addEventListener("click", () => setNotebookSection("clues"));
		els.notebookManualTab.addEventListener("click", () => setNotebookSection("manual"));
		els.notebookManualNotes.addEventListener("input", queueManualNotebookSave);
		els.closeRoleRecordsBtn.addEventListener("click", closeRoleRecords);
		els.roleRecordsModal.addEventListener("click", (event) => {
			if (event.target === els.roleRecordsModal) closeRoleRecords();
		});
		document.addEventListener("keydown", (event) => {
			if (event.key === "Escape" && !els.roleRecordsModal.classList.contains("hidden")) closeRoleRecords();
		});
		els.speechForm.addEventListener("submit", (event) => {
			event.preventDefault();
			if (state.waitingForAgent) return;
			const content = els.speechInput.value.trim();
			if (!content) return;
			if (sendGame({
				type: state.whisper.channel === "private" ? "whisper_speech" : "player_speech",
				content
			})) {
				els.speechInput.value = "";
				setComposerBusy(true);
				setAvatarAction([state.game?.player_role_id, state.whisper.channel === "private" ? state.whisper.activeTargetRoleId : null], state.whisper.channel === "private" ? "private" : "public");
			}
		});
		els.whisperInviteBtn.addEventListener("click", () => {
			if (!els.whisperTarget.value) return;
			sendGame({
				type: "whisper_invite",
				target_role_id: els.whisperTarget.value
			});
		});
		els.whisperCloseBtn.addEventListener("click", () => sendGame({ type: "whisper_close" }));
		els.publicChannelBtn.addEventListener("click", () => setChannel("public"));
		els.privateChannelBtn.addEventListener("click", () => setChannel("private"));
		els.phaseContinueBtn.addEventListener("click", () => {
			if (state.currentPhase === "replay") {
				openRoleRecords();
				return;
			}
			if (state.stageResolution?.vote?.pending) {
				toast("请先完成本幕投票或最终指认");
				setPhaseContinue("完成本幕投票后继续", false);
				return;
			}
			if (sendGame({ type: "advance_phase" })) setPhaseContinue("DM 正在切换环节", false);
		});
		els.submitStageVoteBtn.addEventListener("click", () => {
			if (!state.selectedVoteRoleId) return;
			if (sendGame({
				type: "stage_vote",
				target_role_id: state.selectedVoteRoleId
			})) {
				els.submitStageVoteBtn.disabled = true;
				els.submitStageVoteBtn.innerHTML = "<span>DM 正在汇总全部投票</span><b>·</b>";
			}
		});
		els.advanceBtn.addEventListener("click", () => {
			if (sendGame({ type: "request_phase_end" })) {
				els.advanceBtn.disabled = true;
				els.advanceBtn.textContent = "正在征询所有角色";
				els.investigationEndVoteStatus.className = "end-vote-status pending";
				els.investigationEndVoteStatus.innerHTML = "<strong>结束投票进行中</strong><p>真人已投同意票，角色 Agent 正在独立表态。</p>";
			}
		});
		syncCompactGamePanel();
		authChannel?.addEventListener("message", (event) => {
			if (event.data?.type === "logout") showAuth(false);
		});
		window.addEventListener("pageshow", async (event) => {
			if (!event.persisted || !state.user) return;
			try {
				const user = await api("/api/me");
				authStore.setSession(user);
				state.csrfToken = authStore.csrfToken;
				state.user = authStore.user;
			} catch (_) {
				showAuth();
			}
		});
		window.addEventListener("popstate", () => {
			if (state.user) restoreRoute();
			else {
				const route = appRouter.current();
				if (route.name !== "register" && route.name !== "login") showAuth(true);
			}
		});
		(async function bootstrap() {
			localStorage.removeItem("ai_mm_token");
			try {
				await enterApp(await api("/api/me"));
			} catch (_) {
				showAuth();
			}
		})();
	}
	//#endregion
	//#region src/main.ts
	var pinia = createPinia();
	setActivePinia(pinia);
	var router = createAppRouter();
	var queryClient = new QueryClient({ defaultOptions: {
		queries: {
			staleTime: 3e4,
			retry: 1,
			refetchOnWindowFocus: true
		},
		mutations: { retry: 0 }
	} });
	initializeFrontendRuntime(useAuthStore(), router);
	var app = createApp(App_default);
	app.use(pinia);
	app.use(router);
	app.use(VueQueryPlugin, { queryClient });
	app.mount("#vueRoot");
	router.isReady().then(() => mountLegacyApp());
	//#endregion
})();

//# sourceMappingURL=app.js.map