using Confluent.Kafka.Admin;
using Confluent.Kafka;

namespace Patient_Management_System.Kafka
{
    public class KafkaTopicCreator(IConfiguration config)
    {
        public static readonly string PatientUpdatedTopic = "patient-updated";
        private readonly IConfiguration _config = config;
        public async Task CreateTopics()
        {
            var bootstrapServers = _config["Kafka:BootstrapServers"];
            
            var config = new AdminClientConfig
            {
                BootstrapServers = bootstrapServers
            };

            using var adminClient = new AdminClientBuilder(config).Build();

            try
            {
                await adminClient.CreateTopicsAsync(new[]
                {
                    new TopicSpecification
                    {
                        Name = _config["Kafka:PatientCreatedTopic"],
                        NumPartitions = 1,
                        ReplicationFactor = 1
                    },
                    new TopicSpecification
                    {
                        Name = _config["Kafka:PatientUpdatedTopic"],
                        NumPartitions = 1,
                        ReplicationFactor = 1
                    },
                    new TopicSpecification
                    {
                        Name = _config["Kafka:PatientDeletedTopic"],
                        NumPartitions = 1,
                        ReplicationFactor = 1
                    },
                    new TopicSpecification
                    {
                        Name = _config["Kafka:BillingCreatedTopic"],
                        NumPartitions = 1,
                        ReplicationFactor = 1
                    },
                    new TopicSpecification
                    {
                        Name = "patient-updated",
                        NumPartitions = 1,
                        ReplicationFactor = 3
                    },
                });

                Console.WriteLine("Topic created successfully.");
            }
            catch (CreateTopicsException e)
            {
                if (e.Results[0].Error.Code == ErrorCode.TopicAlreadyExists)
                {
                    Console.WriteLine("Topic already exists. Continuing...");
                }
                else
                {
                    throw;
                }
            }
        }
    }
}