--
-- PostgreSQL database dump
--

\restrict 8GIrCf2ca1JoZohi7cBFTkP1Bv4HBgrj5UcmQPeKoLRREPCXE2A0Kiv3Kt2nwxT

-- Dumped from database version 18.3
-- Dumped by pg_dump version 18.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: sessionstatus; Type: TYPE; Schema: public; Owner: continuum
--

CREATE TYPE public.sessionstatus AS ENUM (
    'ACTIVE',
    'COMPLETED',
    'ABANDONED'
);


ALTER TYPE public.sessionstatus OWNER TO continuum;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: continuum
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO continuum;

--
-- Name: capture_messages; Type: TABLE; Schema: public; Owner: continuum
--

CREATE TABLE public.capture_messages (
    id character varying(36) NOT NULL,
    session_id character varying(36) NOT NULL,
    role character varying(20) NOT NULL,
    content text NOT NULL,
    extracted_entities json,
    "timestamp" timestamp without time zone NOT NULL
);


ALTER TABLE public.capture_messages OWNER TO continuum;

--
-- Name: capture_sessions; Type: TABLE; Schema: public; Owner: continuum
--

CREATE TABLE public.capture_sessions (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    status public.sessionstatus NOT NULL,
    project_name character varying(200),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    completed_at timestamp without time zone
);


ALTER TABLE public.capture_sessions OWNER TO continuum;

--
-- Name: drill_attempts; Type: TABLE; Schema: public; Owner: continuum
--

CREATE TABLE public.drill_attempts (
    id character varying(36) NOT NULL,
    drill_id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    response text NOT NULL,
    score double precision,
    feedback text,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.drill_attempts OWNER TO continuum;

--
-- Name: drills; Type: TABLE; Schema: public; Owner: continuum
--

CREATE TABLE public.drills (
    id character varying(36) NOT NULL,
    title character varying(255) NOT NULL,
    description text NOT NULL,
    scenario text NOT NULL,
    decision_id character varying(36),
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.drills OWNER TO continuum;

--
-- Name: processed_files; Type: TABLE; Schema: public; Owner: continuum
--

CREATE TABLE public.processed_files (
    id character varying(36) NOT NULL,
    file_path character varying(512) NOT NULL,
    file_hash character varying(64) NOT NULL,
    processed_at timestamp without time zone NOT NULL,
    decisions_extracted integer NOT NULL
);


ALTER TABLE public.processed_files OWNER TO continuum;

--
-- Name: users; Type: TABLE; Schema: public; Owner: continuum
--

CREATE TABLE public.users (
    id character varying(36) NOT NULL,
    email character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    name character varying(255),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.users OWNER TO continuum;

--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: continuum
--

COPY public.alembic_version (version_num) FROM stdin;
001_initial
\.


--
-- Data for Name: capture_messages; Type: TABLE DATA; Schema: public; Owner: continuum
--

COPY public.capture_messages (id, session_id, role, content, extracted_entities, "timestamp") FROM stdin;
\.


--
-- Data for Name: capture_sessions; Type: TABLE DATA; Schema: public; Owner: continuum
--

COPY public.capture_sessions (id, user_id, status, project_name, created_at, updated_at, completed_at) FROM stdin;
\.


--
-- Data for Name: drill_attempts; Type: TABLE DATA; Schema: public; Owner: continuum
--

COPY public.drill_attempts (id, drill_id, user_id, response, score, feedback, created_at) FROM stdin;
\.


--
-- Data for Name: drills; Type: TABLE DATA; Schema: public; Owner: continuum
--

COPY public.drills (id, title, description, scenario, decision_id, created_at) FROM stdin;
\.


--
-- Data for Name: processed_files; Type: TABLE DATA; Schema: public; Owner: continuum
--

COPY public.processed_files (id, file_path, file_hash, processed_at, decisions_extracted) FROM stdin;
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: continuum
--

COPY public.users (id, email, password_hash, name, created_at, updated_at) FROM stdin;
anonymous	anonymous@localhost		Anonymous	2026-04-18 20:48:48.257599	2026-04-18 20:48:48.257599
\.


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: continuum
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: capture_messages capture_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: continuum
--

ALTER TABLE ONLY public.capture_messages
    ADD CONSTRAINT capture_messages_pkey PRIMARY KEY (id);


--
-- Name: capture_sessions capture_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: continuum
--

ALTER TABLE ONLY public.capture_sessions
    ADD CONSTRAINT capture_sessions_pkey PRIMARY KEY (id);


--
-- Name: drill_attempts drill_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: continuum
--

ALTER TABLE ONLY public.drill_attempts
    ADD CONSTRAINT drill_attempts_pkey PRIMARY KEY (id);


--
-- Name: drills drills_pkey; Type: CONSTRAINT; Schema: public; Owner: continuum
--

ALTER TABLE ONLY public.drills
    ADD CONSTRAINT drills_pkey PRIMARY KEY (id);


--
-- Name: processed_files processed_files_pkey; Type: CONSTRAINT; Schema: public; Owner: continuum
--

ALTER TABLE ONLY public.processed_files
    ADD CONSTRAINT processed_files_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: continuum
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_processed_files_file_path; Type: INDEX; Schema: public; Owner: continuum
--

CREATE UNIQUE INDEX ix_processed_files_file_path ON public.processed_files USING btree (file_path);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: continuum
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: capture_messages capture_messages_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: continuum
--

ALTER TABLE ONLY public.capture_messages
    ADD CONSTRAINT capture_messages_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.capture_sessions(id);


--
-- Name: capture_sessions capture_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: continuum
--

ALTER TABLE ONLY public.capture_sessions
    ADD CONSTRAINT capture_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: drill_attempts drill_attempts_drill_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: continuum
--

ALTER TABLE ONLY public.drill_attempts
    ADD CONSTRAINT drill_attempts_drill_id_fkey FOREIGN KEY (drill_id) REFERENCES public.drills(id);


--
-- Name: drill_attempts drill_attempts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: continuum
--

ALTER TABLE ONLY public.drill_attempts
    ADD CONSTRAINT drill_attempts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- PostgreSQL database dump complete
--

\unrestrict 8GIrCf2ca1JoZohi7cBFTkP1Bv4HBgrj5UcmQPeKoLRREPCXE2A0Kiv3Kt2nwxT

