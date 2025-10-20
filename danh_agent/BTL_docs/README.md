# Book Inventory API

A RESTful API built with Node.js, Express, and MySQL2 for managing a book inventory system. This API provides endpoints for creating, reading, updating, and deleting book records, as well as managing authors, genres, publishers, orders, user accounts, and notifications.

This API is designed for use in the backend of an e-commerce platform or a library management system, providing a solid foundation for managing all book-related data and operations.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Project Structure](#project-structure)
- [API Endpoints](#api-endpoints)
    - [Book Management](#book-management)
    - [Author Management](#author-management)
    - [Genre Management](#genre-management)
    - [Publisher Management](#publisher-management)
    - [Order Management](#order-management)
    - [Customer Order Management](#customer-order-management)
    - [Publisher Order Management](#publisher-order-management)
    - [User Management](#user-management)
    - [Notification Management](#notification-management)
    - [Order Logs Management](#order-logs-management)
- [API Routes](#api-routes)
    - [Book Management Routes](#book-management-routes)
    - [Author Management Routes](#author-management-routes)
    - [Genre Management Routes](#genre-management-routes)
    - [Publisher Management Routes](#publisher-management-routes)
    - [Order Management Routes](#order-management-routes)
    - [Customer Order Management Routes](#customer-order-management-routes)
    - [Publisher Order Management Routes](#publisher-order-management-routes)
    - [User Management Routes](#user-management-routes)
    - [Notification Management Routes](#notification-management-routes)
    - [Order Logs Management Routes](#order-logs-management-routes)

## Prerequisites

Before you begin, ensure you have met the following requirements:

-   **Node.js**: Version 14 or higher. You can download it from [nodejs.org](https://nodejs.org/).
-   **MySQL**: A MySQL database server instance, with MySQL2 installed.
-   **npm** or **yarn**: A package manager for installing dependencies. (npm comes with Node.js)
-   **`.env` file**: A file for configuration variables with:
    - `DB_HOST`: The hostname of your MySQL server (e.g., `localhost`).
    - `DB_PORT`: The port number your MySQL server is listening on (default is `3306`).
    - `DB_USER`: The username to access your MySQL database (e.g., `root`).
    - `DB_PASSWORD`: The password for your MySQL user.
    - `DB_NAME`: The name of the database (e.g., `ebookstoredb`).
    - `JWT_SECRET`: A strong secret key for signing JWT tokens. (Generate using: `node -e "console.log(require('crypto').randomBytes(64).toString('hex'))"`)

## Installation

1.  **Clone the Repository:**

    ```bash
    git clone https://github.com/TinhAnhGitHub/BTL.git
    cd book-inventory-api
    ```
2.  **Install Dependencies:**

    ```bash
    npm install
    ```

3. **Create a `.env` File**:

    Create a `.env` file in the root directory and add the required environment variables from the [Prerequisites](#prerequisites) section, example:

    ```bash
    DB_HOST=localhost
    DB_PORT=3306
    DB_USER=root
    DB_PASSWORD=<your_mysql_password>
    DB_NAME=ebookstoredb
    JWT_SECRET=<your_jwt_secret_key>
    ```

4.  **Start the Server:**

    ```bash
    npm start
    ```

    The server should now be running at `http://localhost:3000` (or whatever port is set in your code)

## Project Structure

```bash
📄 .env.example
📄 .gitignore
📁 config
    📄 database.js
    📄 viewEngine.js
📁 controllers
    📄 book.controllers.js
📄 index.js
📁 middleware
    📄 auth.js
    📄 error.middleware.js
📁 models
    📄 book.model.js
📁 mysqlScript
    📄 BookstoreDB_SQL.sql
    📄 data.txt
    📄 fixindex.py
    📄 InsertSampleSQL.sql
    📄 sql_query_ebookdb.sql
    📄 tempCodeRunnerFile.py
    📄 webscrap.py
📄 package-lock.json
📄 package.json
📄 README.md
📁 routes
    📄 book.routes.js
    📄 user.routes.js
```

## API Endpoints

Here's a comprehensive breakdown of all the API endpoints:

### Book Management

| **API Name**           | **Functionality**                                                                                                | **Input**                                                                                                                                 | **Output**                                                                                      |
|------------------------|-----------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
| `GET /books`          | Fetches all books from the database.                                                                            | None                                                                                                                                    | JSON array of books or error message.                                                         |
| `GET /books/:book_id`  | Fetches a single book by its `book_id`.                                                                        | **Params**: `book_id` (string)                                                                                                             | JSON object of the book or a 404 error if the book is not found.                              |
| `POST /books`         | Creates a new book and assigns genres to it.                                                                    | **Body**: `title` (string), `price` (number), `author_id` (string), `pu_id` (string), `imageURL` (string), `genre_ids` (array of genre IDs).| JSON object of the newly created book or error message.                                       |
| `PUT /books/:book_id`  | Updates an existing book by `book_id`, including its details and genres.                                        | **Params**: `book_id` (string).<br> **Body**: `title` (string), `price` (number), `author_id` (string), `pu_id` (string), `genre_ids` (array), `imageURL`.| JSON object of the updated book or 404 error if the book is not found.                        |
| `DELETE /books`      | Deletes all books from the database.                                                                            | None                                                                                                                                   | JSON message confirming deletion or error message.                                            |
| `GET /books/filter`     | Filters books based on provided query parameters like title, price range, author, or publisher.               | **Query**: `title` (string), `minPrice` (number), `maxPrice` (number), `author_id` (string), `author_name` (string), `pu_id` (string).       | JSON array of filtered books or error message.                                                |
| `GET /books/search`    | Searches for book titles matching a query string.                                                               | **Query**: `q` (string, required).                                                                                                       | JSON array of matching book titles or error message.                                          |

### Author Management

| **API Name**             | **Functionality**                                                  | **Input**                                                                              | **Output**                                                      |
|--------------------------|--------------------------------------------------------------------|--------------------------------------------------------------------------------------|----------------------------------------------------------------|
| `GET /authors`         | Fetches all authors from the database.                            | None                                                                                 | JSON array of authors or error message.                       |
| `POST /authors`        | Creates a new author with the provided details.                   | **Body**: `name` (string, optional), `dob` (string, optional), `biography` (string, optional).| JSON object with `author_id` (number) and `name` or error message. |
| `PUT /authors/:author_id` | Updates an author's details by `author_id`.                       | **Body**: `author_id` (number, required), `name` (string), `dob` (string), `biography` (string).| JSON object with `author_id` and `name` or 404 error if not found. |
| `DELETE /authors/:author_id`| Deletes an author by their `author_id`.                          | **Params**: `author_id` (number, required).                                           | JSON message confirming deletion or 404 error if not found.   |

### Genre Management

| **API Name**             | **Functionality**                                                  | **Input**                                                                              | **Output**                                                      |
|--------------------------|--------------------------------------------------------------------|--------------------------------------------------------------------------------------|----------------------------------------------------------------|
| `GET /genres`          | Fetches all genres from the database.                             | None                                                                                 | JSON array of genres or error message.                        |
| `POST /genres`          | Creates a new genre with the provided details.                    | **Body**: `genre_name` (string, required), `description` (string, optional).         | JSON object with `genre_id` (number) and `genre_name` or error message. |
| `PUT /genres/:gen_id`    | Updates a genre's details by `gen_id`.                            | **Body**: `gen_id` (number, required), `genre_name` (string, required), `description` (string). | JSON object with `gen_id` and `genre_name` or 404 error if not found. |
| `DELETE /genres/:gen_id` | Deletes a genre by its `gen_id`.                                  | **Params**: `gen_id` (number, required).                                              | JSON message confirming deletion or 404 error if not found.   |

### Publisher Management

| **API Name**             | **Functionality**                                                  | **Input**                                                                                              | **Output**                                                       |
|--------------------------|--------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------|
| `GET /publishers`       | Fetches all publishers from the database.                          | None                                                                                                  | JSON array of publishers or error message.                     |
| `POST /publishers`      | Creates a new publisher with the provided details.                 | **Body**: `pu_name` (string, required), `pu_phone_number` (string, required), `pu_address` (string).  | JSON object with `pu_id` (number) and `pu_name` or error message. |
| `PUT /publishers/:pu_id` | Updates a publisher's details by `pu_id`.                          | **Body**: `pu_id` (number, required), `pu_name` (string, required), `pu_phone_number` (string), `pu_address` (string). | JSON object with `pu_id` and `pu_name` or 404 error if not found. |
| `DELETE /publishers/:pu_id`| Deletes a publisher by its `pu_id`.                                | **Params**: `pu_id` (number, required).                                                             | JSON message confirming deletion or 404 error if not found.    |

### Order Management

| **API Name**                | **Functionality**                                                                                            | **Input**                                                                                                                                                | **Output**                                                                                                  |
|-----------------------------|------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| `GET /orders`              | Fetches all orders, including associated books for each order.                                             | None                                                                                                                                                        | JSON array of orders with book details or error message.                                                 |
| `GET /orders/:username/:order_id`          | Fetches details of a specific order by `username` and `order_id`.                                        | **Params**: `username` (string), `order_id` (number).                                                                                                                              | JSON object with order and book details or error message.                                                 |
| `POST /cart/:username/create`| Creates a new order with books and assigns it to a specific `username`.                                  | **Params**: `username` (string). **Body**: `order_time` (datetime, required), `order_status` (string, required), `books` (array of objects with `book_id` and `quantity`).                                                         | JSON object with order details (`order_id`, `order_time`, `order_status`, `username`, `books`) or error message. |
| `PATCH /order/:username/:order_id/status`| Updates the status of an order and validates stock availability, rolling back if insufficient stock. | **Params**: `username` (string), `order_id` (number). **Body**: `order_status` (string, required).                                                                                        | JSON message confirming update, or error message if validation fails.                                     |
| `DELETE /order/:username/:order_id`           | Deletes a specific order by `order_id` and `username`.                                                   | **Params**: `username` (string). **Body**: `order_id` (number, required).                                                                                              | JSON message confirming deletion, or error message if the order is not found.                             |

### Customer Order Management

| **API Name**                    | **Functionality**                                                        | **Input**                                                                               | **Output**                                                                  |
|---------------------------------|--------------------------------------------------------------------------|----------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| `GET /cart/:username`          | Fetches all orders made by a specific customer.                          | **Params**: `username` (string)                                                         | JSON array of orders for the customer or error message.               |
| `GET /cart/:username`      | Shows all books currently in a user's cart.                              | **Params**: `username` (string)                                                      | JSON array of books in the user's cart or error message.              |
| `PUT /cart/:username`     | Updates the quantity of a book in the user's cart.                     | **Params**: `username` (string), **Body**: `book_id` (number), `quantity` (number): New quantity of the book. | JSON message confirming updated quantity or error message. |
| `POST /cart/:username/remove`   | Deletes a book from the user's cart.                                     | **Params**: `username` (string), **Body**: `book_id` (number): The book to delete.       | JSON message confirming book removal or error message.                |
| `POST /cart/:username/removeCart`| Clears all books in the user's cart.                                     | **Params**: `username` (string)                                                         | JSON message confirming cart clearance or error message.             |
| `POST /cart/:username/insert` | Inserts a book into the user's cart if it is not already there.        | **Params**: `username` (string), **Body**: `book_id` (number): The book to add to the cart. | JSON message confirming book insertion or error message.             |
| `PATCH /cart/:username/clearCart`  | Clears all books in the user's cart.                                     | **Params**: `username` (string)                                                       | JSON message confirming cart clearance or error message.             |

### Publisher Order Management

| **API Name**                    | **Functionality**                                                      | **Input**                                                                 | **Output**                                                                |
|---------------------------------|--------------------------------------------------------------------|-------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| `GET /order_publishers`        | Fetches all orders to the publishers.                              | None                                                                           | JSON array of orders to publishers or error message.                |
| `POST /order_publishers`       | Creates a new order to a publisher.                                | **Body**: `publisher_id` (number), `book_id` (number), `quantity` (number)    | JSON object confirming publisher order creation or error message.  |
| `PATCH /pubisher-order/:pu_order_id/status`   | Updates the status of a publisher's order.                    | **Params**: `pu_order_id` (number), **Body**: `status` (string): The new status of the order. | JSON message confirming update or error message.                    |
| `GET /pubisher-order/:employeeUsername/:pu_order_id`       | Fetches details of a specific publisher order.                    |  **Params**: `employeeUsername` (string), `pu_order_id` (number)                                | JSON object with publisher order details or error message.          |

### User Management

| **API Name**         | **Functionality**                             | **Input**                                                | **Output**                                                     |
|----------------------|----------------------------------------------|----------------------------------------------------------|--------------------------------------------------------------|
| `POST /auth/signup`      | Creates a new user in the system.        | **Body**: `username` (string), `password` (string), `email` (string)  | JSON message confirming registration or error message.              |
| `POST /auth/signin`      | Allows a user to sign in to the system.        | **Body**: `username` (string), `password` (string)             | JSON object with user session/token or error message.                |
| `GET /user/info/:username` | Retrieves profile information of a user. | **Params**: `username` (string): The username of the user.   | JSON object with user profile details or error message.             |

### Notification Management

| **API Name**                                   | **Functionality**                                                              | **Input**                                                       | **Output**                                                                  |
|------------------------------------------------|-------------------------------------------------------------------------------|-----------------------------------------------------------------|---------------------------------------------------------------------------|
| `PATCH /notifications/:notification_id/read`    | Marks a notification as read.                                                 | **Params**: `notification_id` (number): The ID of the notification. | JSON message confirming notification marked as read or error message.     |
| `DELETE /notifications/:notification_id`         | Deletes a specific notification.                                             | **Params**: `notification_id` (number): The ID of the notification. | JSON message confirming notification deletion or error message.          |
| `GET /notifications/employee`              | Fetches all notifications for employees.                                      | None                                                            | JSON array of employee notifications or error message.               |
| `GET /notifications/employee/unread`       | Fetches all unread notifications for employees.                               | None                                                            | JSON array of unread employee notifications or error message.        |
| `GET /notifications/customer/:username`        | Fetches all notifications for a specific customer.                         | **Params**: `username` (string): The username of the customer. | JSON array of customer notifications or error message.               |
| `GET /notifications/customer/:username/unread` | Fetches all unread notifications for a specific customer.                  | **Params**: `username` (string): The username of the customer.   | JSON array of unread customer notifications or error message.        |

### Order Logs Management

| **API Name**                | **Functionality**                                                   | **Input**                                          | **Output**                                                         |
|-----------------------------|---------------------------------------------------------------------|----------------------------------------------------|-------------------------------------------------------------------|
| `GET /order-logs`           | Fetches all order logs.                                            | None                                               | JSON array of all order logs or error message.                   |
| `GET /order-logs/order/:order_id`   | Fetches order logs for a specific order.                            | **Params**: `order_id` (number): The ID of the order. | JSON array of logs for the specific order or error message.      |
| `GET /order-logs/customer/:username` | Fetches order logs for a specific customer.                         | **Params**: `username` (string): The username of the customer. | JSON array of customer’s order logs or error message.            |
| `GET /order-logs/status-history/:order_id`| Fetches the status history of an order.                             | **Params**: `order_id` (number): The ID of the order.   | JSON array of the order's status changes or error message.       |


## API Routes

This section provides a high-level overview of routes and their function.

### Book Management Routes
| Function                                      | Descriptions                                                               | Parameters                                          | Returns                               | Throws                        |
|-----------------------------------------------|---------------------------------------------------------------------------|-----------------------------------------------------|--------------------------------------|-------------------------------|
| GET /books                                         | Fetches all books from the database.                                        | None                                                | List of books                       | None                          |
| GET /books/filter                                   | Filters books based on query parameters like title, price, etc.             | Query parameters (e.g., title, minPrice, maxPrice, author_id) | Filtered list of books              | None                          |
| GET /books/:book_id                                 | Fetches a single book by its book_id.                                       | book_id (in URL)                                     | Single book details                 | Book not found                |
| GET /books/search                                   | Searches books by title based on the searchItem query parameter.           | searchItem (query parameter)                        | List of books matching search       | None                          |
| POST /books                                        | Creates a new book in the database.                                         | Body parameters (e.g., title, author, price)        | Confirmation of book creation       | Validation error              |
| PUT /books/:book_id                               | Updates a book by its book_id with new details.                             | book_id (in URL), body parameters (e.g., title, price) | Confirmation of book update        | Book not found, Validation error |
| DELETE /books/:book_id                              | Deletes a specific book by its book_id.                                     | book_id (in URL)                                     | Confirmation of book deletion       | Book not found                |
| DELETE /books                                      | Deletes all books from the database.                                       | None                                                | Confirmation of all books deletion  | None                          |

### Author Management Routes
| Function                                      | Descriptions                                                               | Parameters                                          | Returns                               | Throws                        |
|-----------------------------------------------|---------------------------------------------------------------------------|-----------------------------------------------------|--------------------------------------|-------------------------------|
| POST /authors                                  | Creates a new author in the database.                                       | Body parameters (e.g., name, bio)                    | Confirmation of author creation     | Validation error              |
| PUT /authors/:author_id                        | Updates an existing author's details.                                      | author_id (in URL), body parameters (e.g., name, bio) | Confirmation of author update       | Author not found, Validation error |
| DELETE /authors/:author_id                     | Deletes a specific author by author_id.                                    | author_id (in URL)                                    | Confirmation of author deletion     | Author not found              |

### Genre Management Routes
| Function                                      | Descriptions                                                               | Parameters                                          | Returns                               | Throws                        |
|-----------------------------------------------|---------------------------------------------------------------------------|-----------------------------------------------------|--------------------------------------|-------------------------------|
| POST /genres                                   | Creates a new genre in the database.                                       | Body parameters (e.g., name, description)            | Confirmation of genre creation      | Validation error              |
| PUT /genres/:gen_id                            | Updates a specific genre by gen_id.                                        | gen_id (in URL), body parameters (e.g., name, description) | Confirmation of genre update        | Genre not found, Validation error |
| DELETE /genres/:gen_id                         | Deletes a specific genre by gen_id.                                        | gen_id (in URL)                                       | Confirmation of genre deletion      | Genre not found               |

### Publisher Management Routes
| Function                                      | Descriptions                                                               | Parameters                                          | Returns                               | Throws                        |
|-----------------------------------------------|---------------------------------------------------------------------------|-----------------------------------------------------|--------------------------------------|-------------------------------|
| POST /publishers                               | Creates a new publisher in the database.                                   | Body parameters (e.g., name, address, description)    | Confirmation of publisher creation  | Validation error              |
| PUT /publishers/:pu_id                         | Updates an existing publisher's details.                                   | pu_id (in URL), body parameters (e.g., name, address) | Confirmation of publisher update    | Publisher not found, Validation error |
| DELETE /publishers/:pu_id                      | Deletes a specific publisher by pu_id.                                     | pu_id (in URL)                                        | Confirmation of publisher deletion  | Publisher not found           |

### Order Management Routes
| Function                                      | Descriptions                                                               | Parameters                                          | Returns                               | Throws                        |
|-----------------------------------------------|---------------------------------------------------------------------------|-----------------------------------------------------|--------------------------------------|-------------------------------|
| GET /orders                                   | Fetches all orders.                                                       | None                                                | List of orders                      | None                          |
| GET /orders/:username/:order_id           | Fetches an order with specific order_id for the user                             | order_id (in URL)                                    | List of orders by user              | None                          |
| PATCH /order/:username/:order_id/status      | Updates the status of a specific order.                                    | username, order_id (in URL), status (in body)        | Confirmation of order status update | Order not found               |
| DELETE /order/:username/:order_id            | Deletes a specific order.                                                   | username, order_id (in URL)                                       | Confirmation of order deletion      | Order not found               |


### Customer Order Management Routes
| Function                                      | Descriptions                                                               | Parameters                                          | Returns                               | Throws                        |
|-----------------------------------------------|---------------------------------------------------------------------------|-----------------------------------------------------|--------------------------------------|-------------------------------|
| POST /cart/:username/create                   | Creates a new order for the user.                                          | username (in URL), order details                     | Confirmation of order creation      | Validation error              |
| GET /cart/:username                           | Fetches all books in the user's cart.                                      | username (in URL)                                    | List of books in cart               | None                          |
| PUT /cart/:username                           | Updates the quantity of books in the user's cart.                          | username (in URL), updated book quantity            | Confirmation of cart update         | None                          |
| POST /cart/:username/remove                   | Removes a book from the user's cart.                                       | username (in URL), book_id                           | Confirmation of book removal        | None                          |
| POST /cart/:username/removeCart               | Clears the user's entire cart.                                             | username (in URL)                                    | Confirmation of cart clearance      | None                          |
| POST /cart/:username/insert                   | Adds a book to the user's cart.                                            | username (in URL), book_id                           | Confirmation of book addition       | None                          |
| PATCH /cart/:username/clearCart               | Clears the user's entire cart.                                             | username (in URL)                                    | Confirmation of cart clearing       | None                          |

### Publisher Order Management Routes
| Function                                      | Descriptions                                                               | Parameters                                          | Returns                               | Throws                        |
|-----------------------------------------------|---------------------------------------------------------------------------|-----------------------------------------------------|--------------------------------------|-------------------------------|
| POST /order_publishers                        | Creates a new order to a publisher.                                        | order details (e.g., book_id, publisher_id)          | Confirmation of publisher order creation | Validation error          |
| PATCH /pubisher-order/:pu_order_id/status     | Updates the status of a publisher order.                                  | pu_order_id (in URL), status (in body)              | Confirmation of publisher order status update | Publisher order not found|

### User Management Routes
| Function                                      | Descriptions                                                               | Parameters                                          | Returns                               | Throws                        |
|-----------------------------------------------|---------------------------------------------------------------------------|-----------------------------------------------------|--------------------------------------|-------------------------------|
| POST /auth/signup                          | Creates a new user in the system.        | user details (e.g., username, password)            | Confirmation of signup     | Validation error              |
| POST /auth/signin                           | Allows a user to sign in to the system.   | user credentials (e.g., username, password)            | User authentication token         | Validation error              |
| GET /user/info/:username                         | Fetches details about a user.                                  | username(in URL)               | User details           | Validation error              |


### Notification Management Routes
| Function                                      | Descriptions                                                               | Parameters                                          | Returns                               | Throws                        |
|-----------------------------------------------|---------------------------------------------------------------------------|-----------------------------------------------------|--------------------------------------|-------------------------------|
| GET /notifications/employee                   | Fetches all employee notifications.                                        | None                                                | List of employee notifications      | None                          |
| GET /notifications/employee/unread            | Fetches all unread employee notifications.                                 | None                                                | List of unread employee notifications | None                        |
| GET /notifications/customer/:username         | Fetches all customer notifications by username.                            | username (in URL)                                    | List of customer notifications      | None                          |
| GET /notifications/customer/:username/unread  | Fetches all unread customer notifications by username.                     | username (in URL)                                    | List of unread customer notifications | None                       |
| PATCH /notifications/:notification_id/read    | Marks a specific notification as read.                                     | notification_id (in URL)                             | Confirmation of read status         | Notification not found        |
| DELETE /notifications/:notification_id        | Deletes a specific notification.                                           | notification_id (in URL)                             | Confirmation of notification deletion | Notification not found     |

### Order Logs Management Routes
| Function                                      | Descriptions                                                               | Parameters                                          | Returns                               | Throws                        |
|-----------------------------------------------|---------------------------------------------------------------------------|-----------------------------------------------------|--------------------------------------|-------------------------------|
| GET /order-logs                               | Fetches all order logs.                                                    | None                                                | List of order logs                  | None                          |
| GET /order-logs/order/:order_id               | Fetches order logs for a specific order by order_id.                       | order_id (in URL)                                    | Order logs for specific order      | Order not found               |
| GET /order-logs/customer/:username            | Fetches order logs for a specific customer by username.                    | username (in URL)                                    | Customer's order logs               | None                          |
| GET /order-logs/status-history/:order_id      | Fetches the status history of a specific order by order_id.                | order_id (in URL)                                    | Order status history               | Order not found               |